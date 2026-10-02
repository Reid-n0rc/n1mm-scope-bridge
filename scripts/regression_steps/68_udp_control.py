# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Optional UDP remote control works through the real CLI, and is off by default (#30)."""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

from regression_core import CheckFailed, Runner, Step, StepContext, run_command, tail


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _ask(port: int, command: str, timeout: float = 0.3) -> dict[str, Any] | None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        try:
            s.sendto(command.encode(), ("127.0.0.1", port))
            reply: dict[str, Any] = json.loads(s.recv(65535))
        except OSError:
            return None
    return reply


def udp_control(runner: Runner = run_command, wait: float = 8.0) -> None:
    port = _free_port()
    replies: dict[str, dict[str, Any] | None] = {}

    def drive() -> None:
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and _ask(port, "ping") is None:
            pass
        for command in ("status", "stop", "start"):
            replies[command] = _ask(port, command, timeout=2)

    driver = threading.Thread(target=drive, name="regression-ctl")
    driver.start()
    code, out = runner(("uv", "run", "n1mm-scope-bridge", "run", "--emulator", "--duration", "6",
                        "--port", str(_free_port()), "--control-port", str(port)))  # fmt: skip
    driver.join(wait)
    if code != 0:
        raise CheckFailed(f"bridge exited {code}:\n{tail(out)}")
    status, stopped, started = (replies.get(c) for c in ("status", "stop", "start"))
    if not (status and status.get("streaming") is True):
        raise CheckFailed(f"status reply wrong: {status}")
    if not (stopped and stopped.get("streaming") is False):
        raise CheckFailed(f"stop reply wrong: {stopped}")
    if not (started and started.get("streaming") is True):
        raise CheckFailed(f"start reply wrong: {started}")
    if _ask(port, "ping") is not None:
        raise CheckFailed("control port still answers after the bridge exited")


def off_by_default(runner: Runner = run_command) -> None:
    code, out = runner(("uv", "run", "n1mm-scope-bridge", "run", "--emulator", "--duration", "1",
                        "--port", str(_free_port())))  # fmt: skip
    if code != 0 or "Remote control" in out:
        raise CheckFailed(f"remote control must be off unless enabled:\n{tail(out)}")


def steps(ctx: StepContext) -> list[Step]:
    return [
        Step("UDP remote control is off by default", action=lambda: off_by_default(ctx.runner)),
        Step("UDP remote control through the CLI", action=lambda: udp_control(ctx.runner)),
    ]
