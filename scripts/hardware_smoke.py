# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Hardware smoke test: stream a real FT-710 through the bridge and check the result.

Development tooling for the bench (not shipped). With nothing else using the
radio's USB scope interface:

    uv run python scripts/hardware_smoke.py --ftdi-lib-dir <folder> --minutes 5 \\
        [--cat-port /dev/cu.usbserial-XXXX0] --report hardware-smoke.md

It opens the FT4222 scope interface (read-only), probes one frame, then runs
the real bridge pipeline (reader, parser, combiner, N1MM encoder, UDP sender)
into a local UDP listener for the given time. It checks that N1MM packets
arrive at the configured rate, that they are valid ``<Spectrum>`` XML whose
edges match the scope's VFO and span, that bad frames and resyncs stay rare,
and (with ``--cat-port``) that the VFO-A frequency read over CAT matches the
scope stream. CAT is used READ-ONLY here (``FA;`` only, through dev_cat.py).

Dry run with the emulator: ``--dry-run --minutes 0.2``.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dev_cat import CatError, DevCat, EmulatorCatPort, connect

from n1mm_scope_bridge.bridge import BridgeConfig, build_pipeline
from n1mm_scope_bridge.cli.common import EMULATOR_FPS
from n1mm_scope_bridge.emulator import Ft710Emulator, RadioState
from n1mm_scope_bridge.n1mm import N1mmSender
from n1mm_scope_bridge.radios.base import ScopeStatus
from n1mm_scope_bridge.radios.ft710 import FT710
from n1mm_scope_bridge.transport.ft4222 import Ft4222Api, Ft4222Error, Ft4222Reader, load_api

CAT_CHECK_EVERY_S = 10.0
MIN_PACKET_RATIO = 0.8
MAX_BAD_RATIO = 0.01
MAX_RESYNCS = 3


class UdpCollector:
    """Receives the bridge's N1MM packets on a loopback port and checks each one."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 21)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.port: int = self.sock.getsockname()[1]
        self.packets = 0
        self.invalid = 0
        self.last_edges_khz: tuple[float, float] | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="smoke-listener")

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data = self.sock.recv(65535)
            except OSError:  # includes the 0.2 s timeout
                continue
            self.packets += 1
            try:
                root = ET.fromstring(data)
                values = (root.findtext("SpectrumData") or "").split(",")
                if root.tag != "Spectrum" or root.findtext("DataCount") != str(len(values)):
                    raise ValueError("not a valid <Spectrum> packet")
                self.last_edges_khz = (
                    float(root.findtext("LowScopeFrequency") or "nan"),
                    float(root.findtext("HighScopeFrequency") or "nan"),
                )
            except (ET.ParseError, ValueError):
                self.invalid += 1

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.sock.close()


@dataclass
class SmokeResult:
    seconds: float = 0.0
    probe: str = ""
    frames_read: int = 0
    emitted: int = 0
    dropped: int = 0
    bad_frames: int = 0
    resyncs: int = 0
    reinits: int = 0
    packets: int = 0
    invalid_packets: int = 0
    edges_khz: tuple[float, float] | None = None
    last_status: ScopeStatus | None = None
    cat_checks: int = 0
    cat_mismatches: list[str] = field(default_factory=list)
    error: str = ""
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def evaluate(result: SmokeResult, rate_hz: float) -> list[str]:
    """Pass/fail criteria for a smoke run (empty list = pass)."""
    failures = []
    if result.error:
        failures.append(f"bridge stopped with an error: {result.error}")
    expected = rate_hz * result.seconds * MIN_PACKET_RATIO
    if result.packets < expected:
        failures.append(f"only {result.packets} N1MM packets, expected at least {expected:.0f}")
    if result.invalid_packets:
        failures.append(f"{result.invalid_packets} invalid <Spectrum> packets")
    if result.frames_read and result.bad_frames / result.frames_read > MAX_BAD_RATIO:
        failures.append(f"{result.bad_frames} bad frames of {result.frames_read}")
    if result.resyncs > MAX_RESYNCS or result.reinits:
        failures.append(f"{result.resyncs} resyncs and {result.reinits} re-opens")
    status = result.last_status
    if status is not None and result.edges_khz is not None and status.edges_verified:
        centre_khz = sum(result.edges_khz) / 2
        if abs(centre_khz - status.vfo_hz / 1000) > 0.5:
            failures.append(f"packet centre {centre_khz} kHz != VFO {status.vfo_hz / 1000} kHz")
    failures += [f"CAT mismatch: {m}" for m in result.cat_mismatches]
    return failures


def _probe(reader: Ft4222Reader, say: Callable[[str], object]) -> str:
    """Open the scope interface and decode one frame (raises Ft4222Error)."""
    reader.open()
    raw = reader.read_frame()
    if raw is None:
        raise Ft4222Error("no frame from the radio")
    probe = FT710.parse(raw).status
    text = f"VFO {probe.vfo_hz} Hz, span {probe.span_hz} Hz, {probe.mode_name}"
    say(f"Probe: {text}")
    return text


def _check_cat(cat: DevCat, status: ScopeStatus, result: SmokeResult) -> None:
    try:
        cat_hz = cat.read_vfo_a_hz()
    except CatError as err:
        result.cat_mismatches.append(f"CAT read failed: {err}")
        return
    result.cat_checks += 1
    if cat_hz != status.vfo_hz:
        result.cat_mismatches.append(f"CAT VFO-A {cat_hz} Hz vs scope {status.vfo_hz} Hz")


def run_smoke(
    api: Ft4222Api,
    *,
    seconds: float,
    rate_hz: float = 4.0,
    cat: DevCat | None = None,
    say: Callable[[str], object] = print,
    clock: Callable[[], float] = time.monotonic,
) -> SmokeResult:
    result = SmokeResult()
    reader = Ft4222Reader(api)
    try:
        result.probe = _probe(reader, say)
    except Ft4222Error as err:
        reader.close()
        result.error = str(err)
        result.failures = [f"probe failed: {err}"]
        return result
    latest: list[ScopeStatus] = []

    def remember(status: ScopeStatus) -> None:
        latest[:] = [status]

    collector = UdpCollector()
    collector.start()
    sender = N1mmSender("127.0.0.1", collector.port)
    pipe = build_pipeline(
        BridgeConfig(FT710, "FT-710 smoke", rate_hz=rate_hz),
        reader,
        sender,
        close_source=reader.stop,
        on_status=remember,
        warn=lambda m: say(f"warning: {m}"),
    )
    start = clock()
    next_cat = start
    pipe.start()
    try:
        while pipe.alive and clock() - start < seconds:
            pipe.join(timeout=0.5)  # re-raises a stream error (USB unplugged, etc.)
            if cat is not None and latest and clock() >= next_cat:
                next_cat = clock() + CAT_CHECK_EVERY_S
                _check_cat(cat, latest[0], result)
    except Exception as err:  # a radio fault is a FAIL result, not a crash
        result.error = str(err)
    finally:
        result.seconds = clock() - start  # streaming time only, not shutdown
        pipe.stop()
        try:
            pipe.join(timeout=5)
        except Exception as err:  # the bridge's own error is the result, not a crash
            result.error = result.error or str(err)
        sender.close()
        time.sleep(0.3)  # let the last datagrams land
        collector.stop()
    stats = pipe.stats()
    result.frames_read, result.emitted = stats.frames_read, stats.emitted
    result.dropped, result.bad_frames = stats.frames_dropped, stats.bad_frames
    result.resyncs, result.reinits = reader.resyncs, reader.reinits
    result.packets, result.invalid_packets = collector.packets, collector.invalid
    result.edges_khz = collector.last_edges_khz
    result.last_status = latest[0] if latest else None
    result.failures = evaluate(result, rate_hz)
    return result


def render_report(result: SmokeResult, meta: dict[str, str]) -> str:
    fps = result.frames_read / result.seconds if result.seconds else 0.0
    lines = [
        "# FT-710 hardware smoke test",
        "",
        f"**Result: {'PASS' if result.passed else 'FAIL'}**",
        "",
        *[f"- {k}: `{v}`" for k, v in meta.items()],
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Probe | {result.probe or '-'} |",
        f"| Duration | {result.seconds:.1f} s |",
        f"| Frames read | {result.frames_read} ({fps:.1f} per second) |",
        f"| N1MM packets sent / received | {result.emitted} / {result.packets} |",
        f"| Invalid packets | {result.invalid_packets} |",
        f"| Dropped / bad frames | {result.dropped} / {result.bad_frames} |",
        f"| Resyncs / re-opens | {result.resyncs} / {result.reinits} |",
        f"| Last packet edges | {result.edges_khz or '-'} kHz |",
        f"| CAT VFO checks / mismatches | {result.cat_checks} / {len(result.cat_mismatches)} |",
    ]
    if result.failures:
        lines += ["", "## Failures", "", *[f"- {f}" for f in result.failures]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--ftdi-lib-dir", help="folder with LibFT4222 (macOS: libft4222.dylib)")
    parser.add_argument("--minutes", type=float, default=5.0)
    parser.add_argument("--rate", type=float, default=4.0, help="N1MM updates per second")
    parser.add_argument("--cat-port", help="optional read-only VFO check over CAT (FA; only)")
    parser.add_argument("--report", type=Path, default=Path("hardware-smoke.md"))
    parser.add_argument("--dry-run", action="store_true", help="use the emulator")
    args = parser.parse_args(argv)
    cat: DevCat | None = None
    if args.dry_run:
        emulator = Ft710Emulator(RadioState(), fps=EMULATOR_FPS)
        api: Ft4222Api = emulator
        cat = DevCat(EmulatorCatPort(emulator), sleep=lambda _: None)
    else:
        try:
            api = load_api(args.ftdi_lib_dir)
            if args.cat_port:
                cat, baud = connect(args.cat_port)
                print(f"CAT connected on {args.cat_port} at {baud} baud (read-only FA;).")
        except (Ft4222Error, CatError, OSError) as err:
            print(f"error: {err}")
            return 1
    try:
        result = run_smoke(api, seconds=args.minutes * 60, rate_hz=args.rate, cat=cat)
    finally:
        if cat is not None:
            cat.close()
    meta = {
        "date (UTC)": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "source": "emulator" if args.dry_run else "FT-710 (FT4222)",
        "platform": sys.platform,
    }
    report = render_report(result, meta)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    return 0 if result.passed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
