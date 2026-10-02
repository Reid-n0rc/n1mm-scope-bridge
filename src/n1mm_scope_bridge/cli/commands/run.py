# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""``run``: stream the radio's scope to N1MM+ (docs/user/cli/run.md)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, TextIO

from n1mm_scope_bridge.bridge import COMBINE_MODES, DEFAULT_RATE_HZ, DEFAULT_SCALING
from n1mm_scope_bridge.cli.common import Context, UserError, open_radio, radio_args
from n1mm_scope_bridge.cli.session import Source, StreamSession
from n1mm_scope_bridge.control import ControlServer, parse_allow
from n1mm_scope_bridge.n1mm import DEFAULT_HOST, DEFAULT_PORT
from n1mm_scope_bridge.radios import get_radio
from n1mm_scope_bridge.settings import Settings, settings_path
from n1mm_scope_bridge.settings import load as load_settings
from n1mm_scope_bridge.transport.replay import CaptureReader

NAME = "run"
HELP = "stream the radio's scope to N1MM+"
ORDER = 10


def register(sub: Any) -> argparse.ArgumentParser:
    p: argparse.ArgumentParser = sub.add_parser(
        NAME,
        help=HELP,
        description="Options not given fall back to --settings (if used), then the defaults.",
    )
    radio_args(p, from_settings=True)
    p.add_argument(
        "--settings",
        nargs="?",
        type=Path,
        const=settings_path(),
        help="use the GUI's saved settings (optionally from PATH)",
    )
    p.add_argument("--replay", type=Path, help="replay a capture file instead of the radio")
    p.add_argument("--loop", action="store_true", help="loop the replay")
    p.add_argument("--fps", type=float, default=20.0, help="replay speed in frames/s")
    p.add_argument("--host", help=f"N1MM+ PC (default {DEFAULT_HOST}, this PC)")
    p.add_argument("--port", type=int, help=f"N1MM+ spectrum UDP port (default {DEFAULT_PORT})")
    p.add_argument("--name", help="source name shown in N1MM+ (default: the radio model)")
    p.add_argument("--rate", type=float, help=f"updates/s to N1MM+ (default {DEFAULT_RATE_HZ:g})")
    p.add_argument("--scaling", type=float, help=f"dB per level (default {DEFAULT_SCALING})")
    p.add_argument("--combine", choices=COMBINE_MODES, help="latest (default), average, or peak")
    p.add_argument("--duration", type=float, help="stop after this many seconds")
    p.add_argument(
        "--control-port",
        type=int,
        help="enable UDP remote control on this port (off by default; loopback only)",
    )
    return p


def resolve_settings(args: argparse.Namespace, err: TextIO) -> Settings:
    """Settings file (if requested) overridden by any options given on the command line."""
    base = Settings()
    if args.settings is not None:
        base, warnings = load_settings(args.settings)
        for warning in warnings:
            print(f"warning: {warning}", file=err)
    overrides = {
        "radio": args.radio,
        "device": args.device,
        "ftdi_lib_dir": args.ftdi_lib_dir,
        "n1mm_host": args.host,
        "n1mm_port": args.port,
        "source_name": args.name,
        "rate_hz": args.rate,
        "scaling": args.scaling,
        "combine": args.combine,
        "control_port": args.control_port,
        "control_enabled": True if args.control_port is not None else None,
    }
    settings = base.replace(**{k: v for k, v in overrides.items() if v is not None})
    if args.name == "":
        raise UserError("--name must not be empty")
    problems = settings.validate()
    if problems:
        raise UserError("; ".join(f"{field}: {why}" for field, why in problems.items()))
    return settings


def run(args: argparse.Namespace, ctx: Context) -> int:
    err = ctx.err
    settings = resolve_settings(args, err)
    args.radio, args.device = settings.radio, settings.device
    args.ftdi_lib_dir = settings.ftdi_lib_dir or None
    profile = get_radio(settings.radio)
    if args.replay is not None:
        replay = CaptureReader(args.replay, fps=args.fps, loop=args.loop)
        if replay.model != profile.model:
            raise UserError(
                f"{args.replay} was recorded from a {replay.model}, not a {profile.model}"
            )

    def make_source() -> Source:
        if args.replay is not None:
            reader = CaptureReader(args.replay, fps=args.fps, loop=args.loop)
            return reader, reader.stop
        radio = open_radio(args, ctx.api_loader)
        return radio, radio.stop

    session = StreamSession(settings, make_source, err, keep_alive=settings.control_enabled)
    server = None
    if settings.control_enabled:
        try:
            server = ControlServer(
                session,
                port=settings.control_port,
                bind=settings.control_bind,
                allow=parse_allow(settings.control_allow),
            ).start()
        except OSError as exc:
            raise UserError(
                f"Could not start remote control on {settings.control_bind}:"
                f"{settings.control_port} ({exc.strerror or exc}). Is the port in use?"
            ) from None
        print(f"Remote control listening on {server.address[0]}:{server.address[1]}", file=err)
    host, port = settings.n1mm_host, settings.n1mm_port
    try:
        session.start()
        print(
            f"Streaming {profile.model} to N1MM+ at {host}:{port} as {settings.effective_name()!r}",
            file=err,
        )
        session.wait(args.duration)
    finally:
        if server is not None:
            server.stop()
    return 0
