# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The PyInstaller Windows app runs (lane:packaging, #6 replaces this placeholder)."""

from __future__ import annotations

from regression_core import PENDING, Step, StepContext


def steps(ctx: StepContext) -> list[Step]:
    return [
        Step("Windows app (PyInstaller) runs", windows_only=True, disabled_reason=f"{PENDING}6")
    ]
