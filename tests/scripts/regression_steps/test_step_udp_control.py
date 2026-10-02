# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import pytest
from regression_core import CheckFailed, Runner, StepContext
from stepload import fake_runner, load_step

from n1mm_scope_bridge.control import ControlServer

step = load_step("68_udp_control")


class Ctl:
    def __init__(self, stop_ok: bool = True) -> None:
        self.streaming = True
        self.stop_ok = stop_ok

    def status(self) -> dict[str, Any]:
        return {"streaming": self.streaming}

    def start(self) -> None:
        self.streaming = True

    def stop(self) -> None:
        self.streaming = not self.stop_ok

    def set_option(self, name: str, value: str | float) -> None:
        pass


def bridge(controller: Ctl | None, code: int = 0, seconds: float = 1.5) -> Runner:
    """Fake `run`: serves remote control on --control-port for a while."""

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        if controller is None or "--control-port" not in cmd:
            return code, "Streaming FT-710"
        port = int(cmd[cmd.index("--control-port") + 1])
        with ControlServer(controller, port=port):
            time.sleep(seconds)
        return code, "Remote control listening"

    return run


def test_udp_control_passes() -> None:
    step.udp_control(bridge(Ctl()), wait=3)


@pytest.mark.parametrize(
    ("runner", "message"),
    [
        (bridge(None, code=0), "status reply wrong"),
        (bridge(Ctl(), code=2), "bridge exited 2"),
        (bridge(Ctl(stop_ok=False)), "stop reply wrong"),
    ],
)
def test_udp_control_failures(runner: Runner, message: str) -> None:
    with pytest.raises(CheckFailed, match=message):
        step.udp_control(runner, wait=0.5)


def test_off_by_default() -> None:
    step.off_by_default(fake_runner())
    with pytest.raises(CheckFailed, match="off unless enabled"):
        step.off_by_default(lambda cmd: (0, "Remote control listening on 127.0.0.1:13070"))


def test_registered() -> None:
    names = [s.name for s in step.steps(StepContext(runner=fake_runner()))]
    assert names == ["UDP remote control is off by default", "UDP remote control through the CLI"]
