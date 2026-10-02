# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Locked clean environment."""

from __future__ import annotations

from regression_core import Step, StepContext


def steps(ctx: StepContext) -> list[Step]:
    gui = ("--no-group", "gui-dev") if ctx.skip_gui else ()
    return [Step("Locked clean environment", ("uv", "sync", "--locked", "--reinstall", *gui))]
