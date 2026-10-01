# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Command-line entry point.

This is a placeholder until the bridge lands (see the roadmap issues on
GitHub). It only reports the version so packaging and CI can be verified.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from n1mm_scope_bridge import __version__

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    print("n1mm-scope-bridge: not implemented yet; see the roadmap issues on GitHub.")
    return 0
