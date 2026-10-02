# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""GUI self-test (#18, #52): the real window streams the emulator to a local listener.

Runs everywhere PySide6 installs (Qt offscreen in CI); free-threaded jobs
skip it with --skip-gui.
"""

from __future__ import annotations

from regression_core import GUI_SKIP, Step, StepContext

COMMAND = ("uv", "run", "n1mm-scope-bridge", "gui", "--self-test")


def steps(ctx: StepContext) -> list[Step]:
    if ctx.skip_gui:
        return [Step("GUI self-test", COMMAND, disabled_reason=GUI_SKIP)]
    return [Step("GUI self-test", COMMAND)]
