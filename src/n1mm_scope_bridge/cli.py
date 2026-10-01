# SPDX-License-Identifier: GPL-3.0-only
"""Command-line entry point.

This is a placeholder until the bridge lands (see the roadmap issues on
GitHub). It only reports the version so packaging and CI can be verified.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from n1mm_scope_bridge import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="n1mm-scope-bridge",
        description="Stream a radio's spectrum scope into N1MM Logger+'s Spectrum Display.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    print("n1mm-scope-bridge: not implemented yet; see the roadmap issues on GitHub.")
    return 0
