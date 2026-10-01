# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Command-line interface: run, record, probe, list-radios.

The GUI (#18) drives the same functions. Errors a user can fix (missing FTDI
library, radio not found, bad capture) print one clear line and exit 1,
without a traceback.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, TextIO

from n1mm_scope_bridge import __version__
from n1mm_scope_bridge.bridge import (
    COMBINE_MODES,
    DEFAULT_RATE_HZ,
    DEFAULT_SCALING,
    BridgeConfig,
    build_pipeline,
)
from n1mm_scope_bridge.n1mm import DEFAULT_HOST, DEFAULT_PORT, N1mmSender
from n1mm_scope_bridge.pipeline import Pipeline
from n1mm_scope_bridge.radios import RADIOS, get_radio
from n1mm_scope_bridge.radios.base import ParsedFrame, ScopeStatus
from n1mm_scope_bridge.transport.ft4222 import (
    DEFAULT_DESCRIPTION,
    Ft4222Api,
    Ft4222Error,
    Ft4222Reader,
    load_api,
)
from n1mm_scope_bridge.transport.replay import CaptureError, CaptureReader, CaptureWriter

SOURCE_URL = "https://github.com/Reid-n0rc/n1mm-scope-bridge"

# Appropriate Legal Notices (GPLv3 section 5(d)).
LEGAL_NOTICE = f"""\
Copyright (C) 2026 Reid Crowe, N0RC
Portions derived from wfview, copyright 2017-2026 Elliott H. Liggett (W6EL)
and Phil Taylor (M0VSE), licensed under the GNU GPLv3.
This program comes with ABSOLUTELY NO WARRANTY. It is free software, licensed
under the GNU General Public License version 3, and you are welcome to
redistribute it under its conditions. Run with --license for details.
Source code: {SOURCE_URL}"""

LICENSE_TEXT = f"""\
n1mm-scope-bridge {__version__}
{LEGAL_NOTICE}

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

The full license text is in the LICENSE file shipped with this program and at
<https://www.gnu.org/licenses/gpl-3.0.html>. The complete corresponding source
code, including the wfview-derived portions (listed in THIRD_PARTY.md), is
available at {SOURCE_URL}."""


class _LicenseAction(argparse.Action):
    def __call__(self, parser: argparse.ArgumentParser, *args: object, **kwargs: object) -> None:
        print(LICENSE_TEXT)
        parser.exit()


def _radio_args(p: argparse.ArgumentParser, *, device: bool = True) -> None:
    p.add_argument("--radio", default="ft710", help="radio model (see list-radios)")
    if device:
        p.add_argument("--ftdi-lib-dir", help="folder containing LibFT4222 and ftd2xx")
        p.add_argument("--device", default=DEFAULT_DESCRIPTION, help="FT4222 device description")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="n1mm-scope-bridge",
        description="Stream a radio's spectrum scope into N1MM Logger+'s Spectrum Display.",
        epilog=LEGAL_NOTICE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}\n{LEGAL_NOTICE}"
    )
    parser.add_argument(
        "--license", action=_LicenseAction, nargs=0, help="show license and warranty details"
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    run = sub.add_parser("run", help="stream the radio's scope to N1MM+")
    _radio_args(run)
    run.add_argument("--replay", type=Path, help="replay a capture file instead of the radio")
    run.add_argument("--loop", action="store_true", help="loop the replay")
    run.add_argument("--fps", type=float, default=20.0, help="replay speed in frames/s")
    run.add_argument("--host", default=DEFAULT_HOST, help="N1MM+ PC (default: this PC)")
    run.add_argument("--port", type=int, default=DEFAULT_PORT, help="N1MM+ spectrum UDP port")
    run.add_argument("--name", help="source name shown in N1MM+ (default: the radio model)")
    run.add_argument("--rate", type=float, default=DEFAULT_RATE_HZ, help="updates/s to N1MM+")
    run.add_argument("--scaling", type=float, default=DEFAULT_SCALING, help="dB per level")
    run.add_argument("--combine", choices=COMBINE_MODES, default="latest")
    run.add_argument("--duration", type=float, help="stop after this many seconds")

    record = sub.add_parser("record", help="save raw scope frames to a capture file")
    _radio_args(record)
    record.add_argument("--frames", type=int, default=50, help="number of frames (default 50)")
    record.add_argument("out", type=Path, help="capture file to write")

    probe = sub.add_parser("probe", help="check the FTDI library and the radio connection")
    _radio_args(probe)

    sub.add_parser("list-radios", help="list supported radios")
    return parser


class LatestStatus:
    """Holds the most recent scope status; written by the sender thread, read by main."""

    def __init__(self) -> None:
        self.value: ScopeStatus | None = None

    def update(self, status: ScopeStatus) -> None:
        self.value = status  # a single reference assignment, safe without the GIL too


class UserError(Exception):
    """A problem the operator can fix; reported without a traceback."""


ApiLoader = Callable[[str | None], Ft4222Api]


def _open_radio(args: argparse.Namespace, api_loader: ApiLoader) -> Ft4222Reader:
    return Ft4222Reader(api_loader(args.ftdi_lib_dir), description=args.device)


def format_status(status: ScopeStatus | None, pipe: Pipeline[Any]) -> str:
    stats = pipe.stats()
    radio = (
        f"VFO {status.vfo_hz / 1e6:.6f} MHz, span {status.span_hz / 1e3:g} kHz, {status.mode_name}"
        if status
        else "waiting for radio"
    )
    return (
        f"{radio} | read {stats.frames_read} | sent {stats.emitted} | "
        f"dropped {stats.frames_dropped} | bad {stats.bad_frames}"
    )


def supervise(
    pipe: Pipeline[Any],
    *,
    duration: float | None,
    report: Callable[[], object],
    clock: Callable[[], float] = time.monotonic,
    interval: float = 1.0,
) -> None:
    """Wait for the pipeline, reporting once per interval; Ctrl-C or duration stops it."""
    deadline = None if duration is None else clock() + duration
    try:
        while pipe.alive:
            pipe.join(
                timeout=interval
                if deadline is None
                else min(interval, max(0.0, deadline - clock()))
            )
            report()
            if deadline is not None and clock() >= deadline:
                break
    except KeyboardInterrupt:
        pass
    finally:
        pipe.stop()
        pipe.join(timeout=5)


def cmd_run(args: argparse.Namespace, api_loader: ApiLoader, err: TextIO) -> int:
    profile = get_radio(args.radio)
    source: Iterable[bytes]
    if args.replay is not None:
        replay = CaptureReader(args.replay, fps=args.fps, loop=args.loop)
        if replay.model != profile.model:
            raise UserError(
                f"{args.replay} was recorded from a {replay.model}, not a {profile.model}"
            )
        source, close = replay, replay.stop
    else:
        radio = _open_radio(args, api_loader)
        source, close = radio, radio.stop
    config = BridgeConfig(
        profile,
        profile.model if args.name is None else args.name,
        scaling=args.scaling,
        rate_hz=args.rate,
        combine=args.combine,
    )
    latest = LatestStatus()
    with N1mmSender(args.host, args.port) as sender:
        pipe = build_pipeline(
            config,
            source,
            sender,
            close_source=close,
            on_status=latest.update,
            warn=lambda m: print(f"warning: {m}", file=err),
        )
        print(
            f"Streaming {profile.model} to N1MM+ at {args.host}:{args.port} as {config.name!r}",
            file=err,
        )
        pipe.start()
        supervise(
            pipe,
            duration=args.duration,
            report=lambda: print(format_status(latest.value, pipe), file=err),
        )
    return 0


def cmd_record(args: argparse.Namespace, api_loader: ApiLoader, err: TextIO) -> int:
    profile = get_radio(args.radio)
    if args.frames < 1:
        raise UserError("--frames must be at least 1")
    radio = _open_radio(args, api_loader)
    with args.out.open("wb") as fh:
        writer = CaptureWriter(fh, profile.model, profile.frame_size)
        for frame in radio:
            writer.write(frame)
            if writer.frames >= args.frames:
                radio.stop()
    print(f"Recorded {writer.frames} frames to {args.out}", file=err)
    return 0


def cmd_probe(args: argparse.Namespace, api_loader: ApiLoader, out: TextIO) -> int:
    profile = get_radio(args.radio)
    radio = _open_radio(args, api_loader)
    print("FTDI libraries loaded.", file=out)
    parsed: ParsedFrame | None = None
    for frame in radio:
        parsed = profile.parse(frame)
        radio.stop()
    assert parsed is not None
    s = parsed.status
    print(f"{profile.model} found on {args.device!r}.", file=out)
    print(f"VFO-A {s.vfo_hz} Hz, span {s.span_hz} Hz, scope mode {s.mode_name}", file=out)
    if not s.edges_verified:
        print("Tip: set the radio's scope to Center mode for exact N1MM frequencies.", file=out)
    return 0


def cmd_list_radios(out: TextIO) -> int:
    for key, profile in sorted(RADIOS.items()):
        print(f"{key:10} {profile.model}", file=out)
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    api_loader: ApiLoader = load_api,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return cmd_run(args, api_loader, err)
        if args.command == "record":
            return cmd_record(args, api_loader, err)
        if args.command == "probe":
            return cmd_probe(args, api_loader, out)
        if args.command == "list-radios":
            return cmd_list_radios(out)
    except (UserError, Ft4222Error, CaptureError, KeyError, ValueError, OSError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"error: {message}", file=err)
        return 1
    parser.print_help(out)
    return 0
