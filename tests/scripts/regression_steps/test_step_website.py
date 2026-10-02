# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from pathlib import Path

import pytest
from regression_core import CheckFailed, StepContext
from stepload import fake_runner, load_step

site = load_step("90_website")


def test_command_without_screenshots(tmp_path: Path) -> None:
    cmd = site.command(tmp_path / "none", tmp_path / "out")
    assert cmd[-2:] == ("--out", str(tmp_path / "out"))
    assert "--screenshots" not in cmd


def test_command_with_screenshots(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    cmd = site.command(tmp_path, tmp_path / "out")
    assert cmd[-2:] == ("--screenshots", str(tmp_path))


def test_build_runs_and_reports_failure(tmp_path: Path) -> None:
    site.build(fake_runner(), tmp_path, tmp_path / "out")
    with pytest.raises(CheckFailed, match="site build failed"):
        site.build(fake_runner({"uv": 1}), tmp_path, tmp_path / "out")


def test_step_is_enabled() -> None:
    (step,) = site.steps(StepContext(runner=fake_runner()))
    assert step.action is not None
    assert not step.disabled_reason
