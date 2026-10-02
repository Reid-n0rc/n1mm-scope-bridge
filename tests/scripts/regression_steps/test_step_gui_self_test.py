# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from regression_core import GUI_SKIP, StepContext
from stepload import fake_runner, load_step

gui = load_step("75_gui_self_test")


def test_runs_the_gui_self_test_through_the_cli() -> None:
    (step,) = gui.steps(StepContext(runner=fake_runner()))
    assert step.command == ("uv", "run", "n1mm-scope-bridge", "gui", "--self-test")
    assert not step.disabled_reason
    assert not step.windows_only


def test_skipped_on_free_threaded_jobs() -> None:
    (step,) = gui.steps(StepContext(runner=fake_runner(), skip_gui=True))
    assert step.disabled_reason == GUI_SKIP
