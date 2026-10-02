# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""``gui``: open the window (docs/user/cli/gui.md). Needs the ``gui`` extra (PySide6)."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
from typing import Any

from n1mm_scope_bridge.cli.common import Context, UserError

NAME = "gui"
HELP = "open the N1MM Scope Bridge window"
ORDER = 15
MISSING_QT = (
    "The window needs PySide6, which is not installed. "
    'Install the GUI with: pip install "n1mm-scope-bridge[gui]"'
)


def register(sub: Any) -> argparse.ArgumentParser:
    p: argparse.ArgumentParser = sub.add_parser(NAME, help=HELP)
    p.add_argument("--settings", type=Path, help="settings file (default: the per-user file)")
    p.add_argument(
        "--self-test",
        action="store_true",
        help="stream the emulator through the window to a local listener and exit 0 on success",
    )
    p.add_argument(
        "--screenshot",
        type=Path,
        metavar="DIR",
        help="save website screenshots of the window and dialogs into DIR, then exit",
    )
    p.add_argument(
        "--record",
        type=Path,
        metavar="DIR",
        help="record a video (MP4/WebM) and GIF of the streaming window into DIR, then exit",
    )
    p.add_argument("--seconds", type=float, help="with --record: length in seconds (default 15)")
    p.add_argument(
        "--fps",
        type=float,
        help="with --record: frames per second (default: the source's own rate, about 11)",
    )
    p.add_argument(
        "--format",
        action="append",
        choices=("mp4", "webm", "gif"),
        help="with --record: output format; repeat for several (default: mp4, webm and gif)",
    )
    p.add_argument(
        "--source",
        choices=("emulator", "radio", "replay"),
        help="with --screenshot/--record: the built-in emulator (default), the radio, "
        "or (--record only) a capture given with --replay",
    )
    p.add_argument("--replay", type=Path, help="with --source replay: a capture from a radio")
    p.add_argument("--ftdi-lib-dir", help="with --source radio: folder with LibFT4222 and D2XX")
    p.add_argument(
        "--settle",
        type=float,
        metavar="SECONDS",
        help="with --source radio: stream this long first so the waterfall fills (default 20)",
    )
    return p


def run(args: argparse.Namespace, ctx: Context) -> int:
    try:
        app = importlib.import_module("n1mm_scope_bridge.gui.app")  # PySide6 is optional
    except ImportError:
        raise UserError(MISSING_QT) from None
    argv: list[str] = []
    if args.settings is not None:
        argv += ["--settings", str(args.settings)]
    if args.self_test:
        argv.append("--self-test")
    if args.screenshot is not None:
        argv += ["--screenshot", str(args.screenshot)]
    if args.record is not None:
        argv += ["--record", str(args.record)]
    if args.seconds is not None:
        argv += ["--seconds", str(args.seconds)]
    if args.fps is not None:
        argv += ["--fps", str(args.fps)]
    for fmt in args.format or ():
        argv += ["--format", fmt]
    if args.source is not None:
        argv += ["--source", args.source]
    if args.replay is not None:
        argv += ["--replay", str(args.replay)]
    if args.ftdi_lib_dir is not None:
        argv += ["--ftdi-lib-dir", args.ftdi_lib_dir]
    if args.settle is not None:
        argv += ["--settle", str(args.settle)]
    return int(app.main(argv))
