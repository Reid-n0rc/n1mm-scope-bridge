# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""``record``: save raw scope frames to a capture file (docs/user/cli/record.md)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from n1mm_scope_bridge.cli.common import Context, UserError, open_radio, radio_args
from n1mm_scope_bridge.radios import get_radio
from n1mm_scope_bridge.transport.replay import CaptureWriter

NAME = "record"
HELP = "save raw scope frames to a capture file"
ORDER = 20


def register(sub: Any) -> argparse.ArgumentParser:
    p: argparse.ArgumentParser = sub.add_parser(NAME, help=HELP)
    radio_args(p)
    p.add_argument("--frames", type=int, default=50, help="number of frames (default 50)")
    p.add_argument("out", type=Path, help="capture file to write")
    return p


def run(args: argparse.Namespace, ctx: Context) -> int:
    profile = get_radio(args.radio)
    if args.frames < 1:
        raise UserError("--frames must be at least 1")
    radio = open_radio(args, ctx.api_loader)
    with args.out.open("wb") as fh:
        writer = CaptureWriter(fh, profile.model, profile.frame_size)
        for frame in radio:
            writer.write(frame)
            if writer.frames >= args.frames:
                radio.stop()
    print(f"Recorded {writer.frames} frames to {args.out}", file=ctx.err)
    return 0
