# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""``list-radios``: list supported radios (docs/user/cli/list-radios.md)."""

from __future__ import annotations

import argparse
from typing import Any

from n1mm_scope_bridge.cli.common import Context
from n1mm_scope_bridge.radios import RADIOS

NAME = "list-radios"
HELP = "list supported radios"
ORDER = 90


def register(sub: Any) -> argparse.ArgumentParser:
    p: argparse.ArgumentParser = sub.add_parser(NAME, help=HELP)
    return p


def run(args: argparse.Namespace, ctx: Context) -> int:
    for key, profile in sorted(RADIOS.items()):
        print(f"{key:10} {profile.model}", file=ctx.out)
    return 0
