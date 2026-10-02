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
    fetch: int = 0,
    probe: tuple[int, str] = (1, step.EXPECTED + " (FT_DEVICE_NOT_FOUND)"),
    arch: str = "amd64",
) -> Runner:
    def run(cmd: Sequence[str]) -> tuple[int, str]:
        if any(part.endswith("fetch_ftdi.py") for part in cmd):
            assert cmd[-2:] == ("--arch", arch)
            return fetch, "fetched"
        assert cmd[-2] == "--ftdi-lib-dir"
        return probe

    return run


def test_passes_with_friendly_no_radio_error(tmp_path: Path) -> None:
    step.real_ftdi_probe(runner(), workdir=tmp_path, platform="win-amd64")


def test_32_bit_python_fetches_the_i386_dlls(tmp_path: Path) -> None:
    step.real_ftdi_probe(runner(arch="i386"), workdir=tmp_path, platform="win32")


def test_arm64_python_explains_the_x64_dll_mismatch(tmp_path: Path) -> None:
    out = step.MISMATCH + " (C:\\ftdi\\LibFT4222-64.dll), but this app runs as ARM64."
    step.real_ftdi_probe(runner(probe=(1, out)), workdir=tmp_path, platform="win-arm64")
    with pytest.raises(CheckFailed, match="expected exit 1"):
        step.real_ftdi_probe(runner(), workdir=tmp_path, platform="win-arm64")


@pytest.mark.parametrize(
    ("platform", "arch"), [("win-amd64", "amd64"), ("win32", "i386"), ("win-arm64", "amd64")]
)
def test_plan_per_architecture(platform: str, arch: str) -> None:
    assert step.plan(platform)[0] == arch
    assert step.plan()[1] in (step.EXPECTED, step.MISMATCH)


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
        step.real_ftdi_probe(runner(**kw), workdir=tmp_path, platform="win-amd64")  # type: ignore[arg-type]


def test_registered_as_windows_only() -> None:
    (only,) = step.steps(StepContext(runner=fake_runner()))
    assert only.windows_only
    assert only.action is not None
