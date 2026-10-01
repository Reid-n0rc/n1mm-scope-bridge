# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""``probe``: check the FTDI library and the radio connection (docs/user/cli/probe.md)."""

from __future__ import annotations

import argparse
from typing import Any

from n1mm_scope_bridge.cli.common import Context, open_radio, radio_args, uses_emulator
from n1mm_scope_bridge.radios import get_radio
from n1mm_scope_bridge.radios.base import ParsedFrame

NAME = "probe"
HELP = "check the FTDI library and the radio connection"
ORDER = 30


def register(sub: Any) -> argparse.ArgumentParser:
    p: argparse.ArgumentParser = sub.add_parser(NAME, help=HELP)
    radio_args(p)
    return p


def run(args: argparse.Namespace, ctx: Context) -> int:
    out = ctx.out
    profile = get_radio(args.radio)
    radio = open_radio(args, ctx.api_loader)
    print(
        "Using the built-in FT-710 emulator." if uses_emulator(args) else "FTDI libraries loaded.",
        file=out,
    )
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
