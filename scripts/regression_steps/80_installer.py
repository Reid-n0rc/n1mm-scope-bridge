# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Installer silent install/run/uninstall (lane:packaging, #20 replaces this placeholder)."""

from __future__ import annotations

from regression_core import PENDING, Step, StepContext


def steps(ctx: StepContext) -> list[Step]:
    return [
        Step(
            "Installer silent install/run/uninstall",
            windows_only=True,
            disabled_reason=f"{PENDING}20",
        )
    ]
