# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from pathlib import Path

import pytest
from regression_core import CheckFailed, StepContext

STEP = Path(__file__).resolve().parents[3] / "scripts" / "regression_steps" / "66_ftdi_download.py"
spec = importlib.util.spec_from_file_location("step_ftdi_download", STEP)
assert spec is not None
assert spec.loader is not None
step = importlib.util.module_from_spec(spec)
spec.loader.exec_module(step)


def runner(code: int, out: str) -> object:
    calls: list[Sequence[str]] = []

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        calls.append(cmd)
        return code, out

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_passes_when_check_ok() -> None:
    run = runner(0, "FTDI download OK: ft4222.whl (HTTP 200, SHA-256 verified)")
    step.ftdi_download(run)
    assert run.calls == [step.CHECK]  # type: ignore[attr-defined]


@pytest.mark.parametrize(("code", "out"), [(1, "FTDI download check FAILED"), (0, "unexpected")])
def test_fails_otherwise(code: int, out: str) -> None:
    with pytest.raises(CheckFailed, match="FTDI download check failed"):
        step.ftdi_download(runner(code, out))


def test_step_registered() -> None:
    steps = step.steps(StepContext(runner=runner(0, "FTDI download OK")))  # type: ignore[arg-type]
    assert steps[0].name.startswith("FTDI library download")
    assert not steps[0].windows_only
