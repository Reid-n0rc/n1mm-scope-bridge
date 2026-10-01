# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Helpers for testing the release regression and its step files (#45)."""

from __future__ import annotations

import importlib.util
import itertools
import socket
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType

from regression_core import Runner

STEPS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "regression_steps"


def load_step(stem: str) -> ModuleType:
    """Import ``scripts/regression_steps/<stem>.py`` (file names start with digits)."""
    spec = importlib.util.spec_from_file_location(
        f"regression_steps.{stem}", STEPS_DIR / f"{stem}.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_runner(codes: dict[str, int] | None = None, output: str = "out") -> Runner:
    calls: list[tuple[str, ...]] = []

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        calls.append(tuple(cmd))
        return (codes or {}).get(cmd[0], 0), output

    run.calls = calls  # type: ignore[attr-defined]
    return run


def ticking() -> Callable[[], float]:
    counter = itertools.count()
    return lambda: float(next(counter))


SPECTRUM = (
    (
        "<Spectrum><app>a</app><Name>FT-710</Name><LowScopeFrequency>1</LowScopeFrequency>"
        "<HighScopeFrequency>2</HighScopeFrequency><ScalingFactor>1</ScalingFactor>"
        "<DataCount>850</DataCount><SpectrumData>{}</SpectrumData></Spectrum>"
    )
    .format(",".join(["7"] * 850))
    .encode()
)


def udp_runner(packets: list[bytes], code: int = 0) -> Runner:
    """Pretends to be the bridge: sends ``packets`` to the --port in the command."""

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        port = int(cmd[cmd.index("--port") + 1])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
            for p in packets:
                tx.sendto(p, ("127.0.0.1", port))
        return code, "bridge output"

    return run
