# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""``ctl``: send one remote-control command to a running bridge (docs/user/cli/ctl.md)."""

from __future__ import annotations

import argparse
import json
from typing import Any

from n1mm_scope_bridge.cli.common import Context, UserError
from n1mm_scope_bridge.control import DEFAULT_CONTROL_PORT, request

NAME = "ctl"
HELP = "send a command to a running bridge (needs remote control enabled)"
ORDER = 60


def register(sub: Any) -> argparse.ArgumentParser:
    p: argparse.ArgumentParser = sub.add_parser(NAME, help=HELP)
    p.add_argument("--host", default="127.0.0.1", help="PC running the bridge (default this PC)")
    p.add_argument(
        "--port", type=int, default=DEFAULT_CONTROL_PORT, help="remote-control port (default 13070)"
    )
    p.add_argument("--timeout", type=float, default=2.0, help="seconds to wait for a reply")
    p.add_argument(
        "request", nargs="+", metavar="REQUEST", help="for example: status, stop, set rate 5"
    )
    return p


def run(args: argparse.Namespace, ctx: Context) -> int:
    command = " ".join(args.request)
    try:
        reply = request(command, host=args.host, port=args.port, timeout=args.timeout)
    except (TimeoutError, OSError):
        raise UserError(
            f"No reply from n1mm-scope-bridge at {args.host}:{args.port}. "
            "Is it running with remote control enabled?"
        ) from None
    print(json.dumps(reply), file=ctx.out)
    return 0 if reply.get("ok") else 1
