# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""GUI self-test (lane:gui, #18 replaces this placeholder)."""

from __future__ import annotations

from regression_core import GUI_SKIP, PENDING, Step, StepContext


def steps(ctx: StepContext) -> list[Step]:
    reason = GUI_SKIP if ctx.skip_gui else f"{PENDING}18"
    return [Step("GUI self-test", windows_only=True, disabled_reason=reason)]
