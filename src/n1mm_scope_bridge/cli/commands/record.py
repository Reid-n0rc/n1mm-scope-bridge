# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""``record``: save raw scope frames to a capture file (docs/user/cli/record.md)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from n1mm_scope_bridge.cli.common import (
    EMULATOR_FPS,
    Context,
    UserError,
    radio_args,
    uses_emulator,
)
from n1mm_scope_bridge.emulator import make_emulator
from n1mm_scope_bridge.radios import get_radio
from n1mm_scope_bridge.transport.ft4222 import Ft4222Api, Ft4222Reader
from n1mm_scope_bridge.transport.replay import CaptureWriter, RawStreamWriter, RecordingApi

NAME = "record"
HELP = "save raw scope frames to a capture file"
ORDER = 20


def register(sub: Any) -> argparse.ArgumentParser:
    p: argparse.ArgumentParser = sub.add_parser(NAME, help=HELP)
    radio_args(p)
    p.add_argument("--frames", type=int, default=50, help="number of frames (default 50)")
    p.add_argument(
        "--raw-stream",
        action="store_true",
        help="save every SPI read before alignment (for checking the emulator, #36)",
    )
    p.add_argument("out", type=Path, help="capture file to write")
    return p


def run(args: argparse.Namespace, ctx: Context) -> int:
    profile = get_radio(args.radio)
    if args.frames < 1:
        raise UserError("--frames must be at least 1")
    api: Ft4222Api = (
        make_emulator(args.scenario or "steady", fps=EMULATOR_FPS)
        if uses_emulator(args)
        else ctx.api_loader(args.ftdi_lib_dir)
    )
    with args.out.open("wb") as fh:
        raw = RawStreamWriter(fh, profile.model, profile.frame_size) if args.raw_stream else None
        writer = None if raw else CaptureWriter(fh, profile.model, profile.frame_size)
        radio = Ft4222Reader(RecordingApi(api, raw) if raw else api, description=args.device)
        frames = 0
        for frame in radio:
            frames += 1
            if writer is not None:
                writer.write(frame)
            if frames >= args.frames:
                radio.stop()
    detail = f" ({raw.chunks} raw reads, {raw.bytes} bytes)" if raw else ""
    print(f"Recorded {frames} frames to {args.out}{detail}", file=ctx.err)
    return 0
