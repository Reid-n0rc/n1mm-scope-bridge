# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Record golden captures from a real Yaesu FT-710 to validate the emulator (issue #36).

Run once at the radio (Windows or macOS), with N1MM+, wfview, flrig and anything
else using the radio's USB scope interface closed:

    uv run python scripts/capture_golden.py --ftdi-lib-dir <folder with LibFT4222>

It walks through a checklist of radio states. For each case you set the radio
as shown, press Enter, and the tool records about 2 seconds of the raw scope
stream, decodes it, and asks you to confirm what the radio displayed. The
tool only READS the scope stream: it never transmits and never changes radio
settings. For the transmit case you key the radio yourself into a dummy load.

Try it without a radio first:

    uv run python scripts/capture_golden.py --dry-run --yes

Unattended mode (development): with ``--auto --cat-port <device>`` the tool sets
the scope span and mode itself over CAT using ``dev_cat.py`` (whitelisted:
it reads VFO-A, span and scope mode and sets ONLY span and scope mode, never
transmits), confirms each case from both the CAT readback and the scope stream,
and restores the original span and mode at the end, even on errors or Ctrl-C.
Operator-only cases (transmit, power-on, USB re-plug) are skipped. Needs the
dev dependency group ``hardware`` (pyserial): ``uv sync --group hardware``.
Dry run of the unattended flow: ``--auto --dry-run``.

Captures are written to tests/fixtures/golden/ (each under 256 KiB) with a
manifest.json; commit them in a PR for #36.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev_cat import CatError, DevCat, EmulatorCatPort, ScopeRestorer, connect

from n1mm_scope_bridge.cli.common import EMULATOR_FPS
from n1mm_scope_bridge.emulator import Ft710Emulator, RadioState
from n1mm_scope_bridge.radios.base import FrameDecoder, SpanUnavailable
from n1mm_scope_bridge.radios.ft710 import FT710
from n1mm_scope_bridge.radios.yaesu_scope import FRAME_SIZE
from n1mm_scope_bridge.transport.ft4222 import Ft4222Api, Ft4222Error, Ft4222Reader, load_api
from n1mm_scope_bridge.transport.replay import (
    RawStreamApi,
    RawStreamWriter,
    RecordingApi,
    read_raw_stream,
)

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
PARSER_FILE = ROOT / "src" / "n1mm_scope_bridge" / "radios" / "yaesu_scope.py"
MAX_FIXTURE_BYTES = 256 * 1024
CASE_SECONDS = 2.0
SETTLE_SECONDS = 1.0
"""Wait after a CAT scope change before recording, so the stream reflects it."""
SCHEMA = 1


@dataclass(frozen=True)
class Case:
    name: str
    instructions: str
    state: RadioState
    """The state the emulator uses for this case in --dry-run."""
    operator_only: bool = False
    """Needs a person at the radio (transmit, power cycle, USB re-plug); --auto skips it."""

    @property
    def auto_span(self) -> int:
        return self.state.span_index

    @property
    def auto_mode(self) -> str:
        """Scope mode code as the parser reports it (first hex digit of status byte 17)."""
        return f"{self.state.scope_mode:X}"[0]


def _cases() -> list[Case]:
    cases = [
        Case(
            f"center-span-{i}",
            f"Scope in Center mode, span {FT710.spans_hz[i] / 1000:g} kHz, on 14.074 MHz USB.",
            RadioState(span_index=i, scope_mode=0x04),
        )
        for i in range(len(FT710.spans_hz))
    ]
    cases += [
        Case(
            "cursor-mode",
            "Scope in Cursor mode, span 20 kHz, 14.074 MHz.",
            RadioState(scope_mode=0x07),
        ),
        Case(
            "fixed-mode",
            "Scope in Fixed mode, span 20 kHz, fixed edges around 14.000-14.350 MHz.",
            RadioState(scope_mode=0x0A),
        ),
        Case(
            "tx-dummy-load",
            "Connect a DUMMY LOAD. After pressing Enter, key the radio yourself at low power "
            "(e.g. 5 W tune carrier) for the whole 2 seconds. This tool never transmits.",
            RadioState(tx=True),
            operator_only=True,
        ),
        Case(
            "power-on-startup",
            "Turn the radio OFF, then ON. As soon as it has booted, press Enter.",
            RadioState(),
            operator_only=True,
        ),
        Case(
            "usb-replug",
            "Unplug the radio's USB cable, plug it back in, wait 3 seconds, then press Enter.",
            RadioState(),
            operator_only=True,
        ),
    ]
    return cases


CASES = _cases()


def git_blob_hash(path: Path) -> str:
    """Same value as `git hash-object <path>` (no git needed)."""
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


@dataclass
class CaptureResult:
    frames: int
    chunks: int
    size: int
    seconds: float
    decoded: dict[str, Any]


def record_case(
    api: Ft4222Api,
    out: Path,
    *,
    seconds: float = CASE_SECONDS,
    max_bytes: int = MAX_FIXTURE_BYTES,
    clock: Callable[[], float] = time.monotonic,
) -> CaptureResult:
    """Record one raw capture through the normal reader; stop at the time or size limit."""
    buf = io.BytesIO()
    writer = RawStreamWriter(buf, FT710.model, FRAME_SIZE, clock=clock)
    reader = Ft4222Reader(RecordingApi(api, writer))
    start = clock()
    frames = 0
    for _ in reader:
        frames += 1
        if clock() - start >= seconds or buf.tell() + FRAME_SIZE * 2 > max_bytes:
            reader.stop()
    out.write_bytes(buf.getvalue())
    _, _, chunks = read_raw_stream(out)
    return CaptureResult(frames, len(chunks), out.stat().st_size, clock() - start, decode(out))


def decode(path: Path) -> dict[str, Any]:
    """What the bridge decodes from a raw capture (first and last whole frame)."""
    _, _, chunks = read_raw_stream(path)
    reader = Ft4222Reader(RawStreamApi(chunks))
    decoder = FrameDecoder(FT710)
    parsed = []
    unavailable = 0  # frames whose mode doesn't report the span (no Center frame before them)
    resyncs = 0  # resyncs needed before the last whole frame (not the end-of-file attempts)
    try:
        for raw in reader:
            try:
                parsed.append(decoder(raw))
            except SpanUnavailable:
                unavailable += 1
            resyncs = reader.resyncs
    except Ft4222Error:
        pass  # the capture ends mid-stream; whole frames so far are what matters
    if not parsed:
        return {"frames": 0, "span_unavailable_frames": unavailable}
    first, last = parsed[0].status, parsed[-1].status
    return {
        "frames": len(parsed),
        "span_unavailable_frames": unavailable,
        "resyncs": resyncs,
        "vfo_hz": last.vfo_hz,
        "span_hz": last.span_hz,
        "mode_name": last.mode_name,
        "mode_family": last.mode_family,
        "mode_code": getattr(last, "scope_mode_code", ""),
        "first_vfo_hz": first.vfo_hz,
    }


Ask = Callable[[str], str]


def run_session(  # noqa: PLR0913 - collaborators injected for tests and dry runs
    api_factory: Callable[[Case], Ft4222Api],
    out_dir: Path,
    *,
    ask: Ask,
    say: Callable[[str], object],
    auto_yes: bool,
    dry_run: bool,
    cases: list[Case] | None = None,
    seconds: float = CASE_SECONDS,
    cat: DevCat | None = None,
    firmware: str | None = None,
    settle: Callable[[], object] = lambda: time.sleep(SETTLE_SECONDS),
) -> dict[str, Any]:
    """Record every case. With ``cat`` (unattended mode) the tool sets the scope span
    and mode itself, confirms each case from CAT readback and the scope stream, skips
    operator-only cases, and always restores the radio's original span and mode."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if firmware is None:
        firmware = "emulator" if dry_run else ask("Radio main firmware version (Menu > Version): ")
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "radio": FT710.model,
        "firmware": firmware.strip() or "unknown",
        "dry_run": dry_run,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "validated_against": git_blob_hash(PARSER_FILE),
        "mode": "auto" if cat is not None else "interactive",
        "cases": [],
    }
    if cat is not None:
        with ScopeRestorer(cat) as original:
            manifest["original_scope"] = {"span_index": original.span_index, "mode": original.mode}
            manifest["vfo_a_hz"] = cat.read_vfo_a_hz()
            for n, case in enumerate(cases or CASES, 1):
                say(f"\n[{n}/{len(cases or CASES)}] {case.name} (auto)")
                manifest["cases"].append(
                    _auto_case(case, cat, api_factory, out_dir, say, seconds, settle)
                )
        say(
            f"Restored the radio's scope to span index {original.span_index}, mode {original.mode}."
        )
        _write_manifest(out_dir, manifest, say)
        return manifest
    for n, case in enumerate(cases or CASES, 1):
        say(f"\n[{n}/{len(cases or CASES)}] {case.name}\n  {case.instructions}")
        if not auto_yes and ask("  Press Enter to record (or type 's' to skip): ").strip() == "s":
            manifest["cases"].append({"name": case.name, "skipped": True})
            continue
        path = out_dir / f"{case.name}.raw"
        try:
            result = record_case(api_factory(case), path, seconds=seconds)
        except Ft4222Error as err:
            say(f"  Could not record: {err}")
            manifest["cases"].append({"name": case.name, "error": str(err)})
            continue
        d = result.decoded
        summary = (
            f"VFO {d.get('vfo_hz', 0) / 1e6:.6f} MHz, span {d.get('span_hz', 0) / 1e3:g} kHz, "
            f"{d.get('mode_name', '?')}"
            if d.get("frames")
            else "no whole frames decoded"
        )
        say(f"  Recorded {result.frames} frames, {result.size} bytes. Decoded: {summary}")
        answer = "y" if auto_yes else ask("  Does the radio show that? [y/n, or type a note]: ")
        manifest["cases"].append(
            {
                "name": case.name,
                "file": path.name,
                "confirmed": answer.strip().lower() in ("y", "yes"),
                "operator_note": ""
                if answer.strip().lower() in ("y", "yes", "")
                else answer.strip(),
                "frames": result.frames,
                "chunks": result.chunks,
                "bytes": result.size,
                "seconds": round(result.seconds, 3),
                "decoded": d,
            }
        )
    _write_manifest(out_dir, manifest, say)
    return manifest


def _write_manifest(out_dir: Path, manifest: dict[str, Any], say: Callable[[str], object]) -> None:
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    say(f"\nWrote {len(manifest['cases'])} cases and manifest.json to {out_dir}")


def _auto_case(
    case: Case,
    cat: DevCat,
    api_factory: Callable[[Case], Ft4222Api],
    out_dir: Path,
    say: Callable[[str], object],
    seconds: float,
    settle: Callable[[], object],
) -> dict[str, Any]:
    """Set the scope for ``case`` over CAT, record it, and confirm it two ways."""
    if case.operator_only:
        say("  Skipped: needs an operator at the radio.")
        return {"name": case.name, "skipped": True, "reason": "operator-only"}
    try:
        cat.set_scope_mode(case.auto_mode)
        cat.set_span_index(case.auto_span)
        settle()
        cat_state = {"span_index": cat.read_span_index(), "mode": cat.read_scope_mode()}
        path = out_dir / f"{case.name}.raw"
        result = record_case(api_factory(case), path, seconds=seconds)
    except (CatError, Ft4222Error) as err:
        say(f"  Could not record: {err}")
        return {"name": case.name, "error": str(err)}
    d = result.decoded
    from_stream = bool(d.get("frames")) and (
        d.get("span_hz") == FT710.spans_hz[case.auto_span] and d.get("mode_code") == case.auto_mode
    )
    from_cat = cat_state == {"span_index": case.auto_span, "mode": case.auto_mode}
    confirmed = from_stream and from_cat
    say(
        f"  Recorded {result.frames} frames. Scope stream {'OK' if from_stream else 'MISMATCH'}, "
        f"CAT readback {'OK' if from_cat else 'MISMATCH'}."
    )
    return {
        "name": case.name,
        "file": path.name,
        "confirmed": confirmed,
        "confirmed_by": "cat+scope-stream" if confirmed else "",
        "expected": {"span_index": case.auto_span, "mode": case.auto_mode},
        "cat_readback": cat_state,
        "frames": result.frames,
        "chunks": result.chunks,
        "bytes": result.size,
        "seconds": round(result.seconds, 3),
        "decoded": d,
    }


def _emulator_for(case: Case) -> Ft4222Api:
    return Ft710Emulator(RadioState(**vars(case.state)), fps=EMULATOR_FPS)


def main(argv: list[str] | None = None, *, ask: Ask = input) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--ftdi-lib-dir", help="folder with LibFT4222 (macOS: libft4222.dylib)")
    parser.add_argument("--dry-run", action="store_true", help="use the emulator, not the radio")
    parser.add_argument("--yes", action="store_true", help="don't prompt (dry runs and tests)")
    parser.add_argument("--out", type=Path, help=f"output folder (default {GOLDEN_DIR})")
    parser.add_argument("--only", nargs="*", help="record only these case names")
    parser.add_argument("--seconds", type=float, default=CASE_SECONDS, help="seconds per case")
    parser.add_argument(
        "--auto", action="store_true", help="unattended: set span/mode over CAT (dev_cat.py)"
    )
    parser.add_argument("--cat-port", help="--auto: the radio's CAT (Enhanced) serial port")
    parser.add_argument("--firmware", help="radio firmware version for the manifest")
    args = parser.parse_args(argv)
    if args.auto and not args.dry_run and not args.cat_port:
        print("error: --auto needs --cat-port (the radio's CAT/Enhanced port)")
        return 1
    if args.dry_run and args.out is None:
        args.out = Path("golden-dry-run")  # never overwrite real fixtures with emulator data
    out_dir = args.out or GOLDEN_DIR
    cases = [c for c in CASES if not args.only or c.name in args.only]
    if not cases:
        print(f"error: no cases match {args.only}; choose from {[c.name for c in CASES]}")
        return 1
    cat: DevCat | None = None
    if args.auto and args.dry_run:
        emulator = Ft710Emulator(RadioState(), fps=EMULATOR_FPS)
        cat = DevCat(EmulatorCatPort(emulator), sleep=lambda _: None)
        factory: Callable[[Case], Ft4222Api] = _iter_same(emulator)
    elif args.dry_run:
        factory = _emulator_for
    else:
        try:
            real = load_api(args.ftdi_lib_dir)
        except Ft4222Error as err:
            print(f"error: {err}")
            return 1
        factory = _iter_same(real)
        if args.auto:
            try:
                cat, baud = connect(args.cat_port)
            except (CatError, OSError) as err:
                print(f"error: {err}")
                return 1
            print(f"CAT connected on {args.cat_port} at {baud} baud (span/mode only).")
    try:
        _run(args, factory, out_dir, cases, cat, ask)
    finally:
        if cat is not None:
            cat.close()
    return 0


def _run(
    args: argparse.Namespace,
    factory: Callable[[Case], Ft4222Api],
    out_dir: Path,
    cases: list[Case],
    cat: DevCat | None,
    ask: Ask,
) -> None:
    run_session(
        factory,
        out_dir,
        ask=ask,
        say=print,
        auto_yes=args.yes or args.auto,
        dry_run=args.dry_run,
        cases=cases,
        seconds=args.seconds,
        cat=cat,
        firmware=args.firmware or ("emulator" if args.dry_run else None),
        settle=(lambda: None) if args.dry_run else (lambda: time.sleep(SETTLE_SECONDS)),
    )


def _iter_same(api: Ft4222Api) -> Callable[[Case], Ft4222Api]:
    """The real radio is the same device for every case."""

    def factory(_: Case) -> Ft4222Api:
        return api

    return factory


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
