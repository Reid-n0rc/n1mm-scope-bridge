# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Command-line interface. Each command is a module in ``cli/commands/``.

The GUI (#18) drives the same functions. Errors a user can fix (missing FTDI
library, radio not found, bad capture) print one clear line and exit 1,
without a traceback.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from collections.abc import Sequence
from types import ModuleType
from typing import TextIO

from n1mm_scope_bridge import __version__
from n1mm_scope_bridge.cli import commands as _commands_pkg
from n1mm_scope_bridge.cli.common import (
    ApiLoader,
    Context,
    LatestStatus,
    UserError,
    format_status,
    supervise,
)
from n1mm_scope_bridge.legal import DISCLAIMER, SHORT_DISCLAIMER
from n1mm_scope_bridge.transport.ft4222 import Ft4222Error, load_api
from n1mm_scope_bridge.transport.replay import CaptureError

__all__ = [
    "LEGAL_NOTICE",
    "LICENSE_TEXT",
    "LatestStatus",
    "UserError",
    "build_parser",
    "discover_commands",
    "format_status",
    "main",
    "supervise",
]

SOURCE_URL = "https://github.com/Reid-n0rc/n1mm-scope-bridge"

# Appropriate Legal Notices (GPLv3 section 5(d)).
LEGAL_NOTICE = f"""\
Copyright (C) 2026 Reid Crowe, N0RC
Portions derived from wfview, copyright 2017-2026 Elliott H. Liggett (W6EL)
and Phil Taylor (M0VSE), licensed under the GNU GPLv3.
This program comes with ABSOLUTELY NO WARRANTY. It is free software, licensed
under the GNU General Public License version 3, and you are welcome to
redistribute it under its conditions. Run with --license for details.
Source code: {SOURCE_URL}
{SHORT_DISCLAIMER}"""

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
available at {SOURCE_URL}.

{DISCLAIMER}"""

_REQUIRED = ("NAME", "HELP", "ORDER", "register", "run")


class _LicenseAction(argparse.Action):
    def __call__(self, parser: argparse.ArgumentParser, *args: object, **kwargs: object) -> None:
        print(LICENSE_TEXT)
        parser.exit()


def discover_commands(package: ModuleType = _commands_pkg) -> dict[str, ModuleType]:
    """Command modules in ``package``, keyed by command name, in ``ORDER``."""
    found: list[ModuleType] = []
    for info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        missing = [attr for attr in _REQUIRED if not hasattr(module, attr)]
        if missing:
            raise RuntimeError(f"CLI command module {module.__name__} lacks {', '.join(missing)}")
        found.append(module)
    found.sort(key=lambda m: (m.ORDER, m.NAME))
    commands = {m.NAME: m for m in found}
    if len(commands) != len(found):
        raise RuntimeError("two CLI command modules use the same NAME")
    return commands


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
    for module in discover_commands().values():
        module.register(sub)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    api_loader: ApiLoader = load_api,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    ctx = Context(api_loader=api_loader, out=out or sys.stdout, err=err or sys.stderr)
    parser = build_parser()
    args = parser.parse_args(argv)
    command = discover_commands().get(args.command or "")
    if command is None:
        parser.print_help(ctx.out)
        return 0
    try:
        code: int = command.run(args, ctx)
    except (UserError, Ft4222Error, CaptureError, KeyError, ValueError, OSError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"error: {message}", file=ctx.err)
        return 1
    return code
