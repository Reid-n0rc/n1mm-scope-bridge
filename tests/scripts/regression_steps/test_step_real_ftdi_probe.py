# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from regression_core import CheckFailed, Runner, StepContext
from stepload import fake_runner, load_step

step = load_step("67_real_ftdi_probe")


def runner(
    fetch: int = 0, probe: tuple[int, str] = (1, step.EXPECTED + " (FT_DEVICE_NOT_FOUND)")
) -> Runner:
    def run(cmd: Sequence[str]) -> tuple[int, str]:
        if any(part.endswith("fetch_ftdi.py") for part in cmd):
            return fetch, "fetched"
        assert cmd[-2] == "--ftdi-lib-dir"
        return probe

    return run


def test_passes_with_friendly_no_radio_error(tmp_path: Path) -> None:
    step.real_ftdi_probe(runner(), workdir=tmp_path)


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"fetch": 1}, "could not fetch"),
        ({"probe": (0, "FT-710 found")}, "expected exit 1"),
        ({"probe": (1, "error: Could not load FTDI")}, "expected exit 1"),
        ({"probe": (1, step.EXPECTED + "\nTraceback (most recent call last)")}, "traceback"),
    ],
)
def test_failures(tmp_path: Path, kw: dict[str, object], message: str) -> None:
    with pytest.raises(CheckFailed, match=message):
        step.real_ftdi_probe(runner(**kw), workdir=tmp_path)  # type: ignore[arg-type]


def test_registered_as_windows_only() -> None:
    (only,) = step.steps(StepContext(runner=fake_runner()))
    assert only.windows_only
    assert only.action is not None
