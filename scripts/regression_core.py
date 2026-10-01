# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Types and helpers shared by the release regression and its step files (#45).

Step files live in ``scripts/regression_steps/NN_name.py``. Each one defines
``steps(ctx: StepContext) -> list[Step]`` and is run in filename order. A new
check is a new file; ``release_regression.py`` never needs editing.
Standard library only.
"""

from __future__ import annotations

import socket
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "regression"
OUTPUT_TAIL = 40
MIN_PACKETS = 5
DRAIN_TIMEOUT = 0.5
SPECTRUM_BINS = 850
GUI_SKIP = "skipped: no PySide6 wheels for free-threaded Python (--skip-gui)"
PENDING = "added by #"
"""Prefix of ``disabled_reason`` for placeholder steps whose feature has not landed."""


class CheckFailed(Exception):
    """A callable step found a problem."""


Action = Callable[[], None]
Runner = Callable[[Sequence[str]], tuple[int, str]]


@dataclass(frozen=True)
class Step:
    name: str
    command: tuple[str, ...] = ()
    action: Action | None = None
    windows_only: bool = False
    disabled_reason: str = ""


@dataclass(frozen=True)
class Result:
    name: str
    status: str  # PASS, FAIL, SKIPPED, NOT RUN
    seconds: float = 0.0
    detail: str = ""
    command: str = ""


@dataclass(frozen=True)
class StepContext:
    """What every step file receives."""

    runner: Runner
    skip_gui: bool = False


def run_command(command: Sequence[str]) -> tuple[int, str]:  # pragma: no cover - real processes
    proc = subprocess.run(
        list(command), cwd=ROOT, capture_output=True, text=True, check=False, errors="replace"
    )
    return proc.returncode, proc.stdout + proc.stderr


def tail(text: str, lines: int = OUTPUT_TAIL) -> str:
    return "\n".join(text.rstrip().splitlines()[-lines:])


def udp_listener() -> socket.socket:
    """A loopback UDP socket standing in for N1MM+ (caller closes it)."""
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 21)
    rx.bind(("127.0.0.1", 0))
    return rx


def drain(rx: socket.socket) -> list[bytes]:
    """Read until the socket is quiet; loopback delivery can lag the sender slightly."""
    rx.settimeout(DRAIN_TIMEOUT)
    packets = []
    while True:
        try:
            packets.append(rx.recv(65535))
        except OSError:  # includes TimeoutError
            return packets
