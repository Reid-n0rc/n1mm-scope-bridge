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
    return int(app.main(argv))
