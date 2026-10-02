# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Helpers shared by the CLI commands (``cli/commands/*.py``)."""

from __future__ import annotations

import argparse
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TextIO

from n1mm_scope_bridge.emulator import SCENARIOS, make_emulator
from n1mm_scope_bridge.pipeline import Pipeline
from n1mm_scope_bridge.radios.base import ScopeStatus
from n1mm_scope_bridge.transport.ft4222 import DEFAULT_DESCRIPTION, Ft4222Api, Ft4222Reader

EMULATOR_FPS = 11.2  # measured on a real FT-710 (#111)

ApiLoader = Callable[[str | None], Ft4222Api]


class UserError(Exception):
    """A problem the operator can fix; reported without a traceback."""


@dataclass(frozen=True)
class Context:
    """What every command receives besides its parsed arguments."""

    api_loader: ApiLoader
    out: TextIO
    err: TextIO


def radio_args(p: argparse.ArgumentParser, *, from_settings: bool = False) -> None:
    """Options shared by commands that talk to a radio (or the emulator)."""
    # With from_settings, unset options fall back to the settings file (see the run command).
    p.add_argument(
        "--radio", default=None if from_settings else "ft710", help="radio model (see list-radios)"
    )
    p.add_argument("--ftdi-lib-dir", help="folder containing LibFT4222 and ftd2xx")
    p.add_argument(
        "--device",
        default=None if from_settings else DEFAULT_DESCRIPTION,
        help="FT4222 device description",
    )
    p.add_argument(
        "--emulator", action="store_true", help="use the built-in FT-710 emulator (no radio needed)"
    )
    p.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        help="emulator scenario (implies --emulator; default: steady)",
    )


def uses_emulator(args: argparse.Namespace) -> bool:
    return bool(args.emulator or args.scenario)


def open_radio(args: argparse.Namespace, api_loader: ApiLoader) -> Ft4222Reader:
    if uses_emulator(args):
        api: Ft4222Api = make_emulator(args.scenario or "steady", fps=EMULATOR_FPS)
    else:
        api = api_loader(args.ftdi_lib_dir)
    return Ft4222Reader(api, description=args.device)


class LatestStatus:
    """Holds the most recent scope status; written by the sender thread, read by main."""

    def __init__(self) -> None:
        self.value: ScopeStatus | None = None

    def update(self, status: ScopeStatus) -> None:
        self.value = status  # a single reference assignment, safe without the GIL too


def format_status(status: ScopeStatus | None, pipe: Pipeline[Any]) -> str:
    stats = pipe.stats()
    radio = (
        f"VFO {status.vfo_hz / 1e6:.6f} MHz, span {status.span_hz / 1e3:g} kHz, {status.mode_name}"
        if status
        else "waiting for radio"
    )
    return (
        f"{radio} | read {stats.frames_read} | sent {stats.emitted} | "
        f"dropped {stats.frames_dropped} | bad {stats.bad_frames}"
    )


def supervise(
    pipe: Pipeline[Any],
    *,
    duration: float | None,
    report: Callable[[], object],
    clock: Callable[[], float] = time.monotonic,
    interval: float = 1.0,
) -> None:
    """Wait for the pipeline, reporting once per interval; Ctrl-C or duration stops it."""
    deadline = None if duration is None else clock() + duration
    try:
        # Ctrl-C is the normal way to stop a running bridge; it is not an error.
        with contextlib.suppress(KeyboardInterrupt):
            while pipe.alive:
                pipe.join(
                    timeout=interval
                    if deadline is None
                    else min(interval, max(0.0, deadline - clock()))
                )
                report()
                if deadline is not None and clock() >= deadline:
                    break
    finally:
        pipe.stop()
        pipe.join(timeout=5)
