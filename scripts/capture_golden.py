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

from n1mm_scope_bridge.cli.common import EMULATOR_FPS
from n1mm_scope_bridge.emulator import Ft710Emulator, RadioState
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
SCHEMA = 1


@dataclass(frozen=True)
class Case:
    name: str
    instructions: str
    state: RadioState
    """The state the emulator uses for this case in --dry-run."""


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
        ),
        Case(
            "power-on-startup",
            "Turn the radio OFF, then ON. As soon as it has booted, press Enter.",
            RadioState(),
        ),
        Case(
            "usb-replug",
            "Unplug the radio's USB cable, plug it back in, wait 3 seconds, then press Enter.",
            RadioState(),
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
    parsed = []
    resyncs = 0  # resyncs needed before the last whole frame (not the end-of-file attempts)
    try:
        for raw in reader:
            parsed.append(FT710.parse(raw))
            resyncs = reader.resyncs
    except Ft4222Error:
        pass  # the capture ends mid-stream; whole frames so far are what matters
    if not parsed:
        return {"frames": 0}
    first, last = parsed[0].status, parsed[-1].status
    return {
        "frames": len(parsed),
        "resyncs": resyncs,
        "vfo_hz": last.vfo_hz,
        "span_hz": last.span_hz,
        "mode_name": last.mode_name,
        "mode_family": last.mode_family,
        "first_vfo_hz": first.vfo_hz,
    }


Ask = Callable[[str], str]


def run_session(
    api_factory: Callable[[Case], Ft4222Api],
    out_dir: Path,
    *,
    ask: Ask,
    say: Callable[[str], object],
    auto_yes: bool,
    dry_run: bool,
    cases: list[Case] | None = None,
    seconds: float = CASE_SECONDS,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    firmware = "emulator" if dry_run else ask("Radio main firmware version (Menu > Version): ")
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "radio": FT710.model,
        "firmware": firmware.strip() or "unknown",
        "dry_run": dry_run,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "validated_against": git_blob_hash(PARSER_FILE),
        "cases": [],
    }
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
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    say(f"\nWrote {len(manifest['cases'])} cases and manifest.json to {out_dir}")
    return manifest


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
    args = parser.parse_args(argv)
    if args.dry_run and args.out is None:
        args.out = Path("golden-dry-run")  # never overwrite real fixtures with emulator data
    out_dir = args.out or GOLDEN_DIR
    cases = [c for c in CASES if not args.only or c.name in args.only]
    if not cases:
        print(f"error: no cases match {args.only}; choose from {[c.name for c in CASES]}")
        return 1
    if args.dry_run:
        factory: Callable[[Case], Ft4222Api] = _emulator_for
    else:
        try:
            real = load_api(args.ftdi_lib_dir)
        except Ft4222Error as err:
            print(f"error: {err}")
            return 1
        factory = _iter_same(real)
    run_session(
        factory,
        out_dir,
        ask=ask,
        say=print,
        auto_yes=args.yes,
        dry_run=args.dry_run,
        cases=cases,
        seconds=args.seconds,
    )
    return 0


def _iter_same(api: Ft4222Api) -> Callable[[Case], Ft4222Api]:
    """The real radio is the same device for every case."""

    def factory(_: Case) -> Ft4222Api:
        return api

    return factory


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
