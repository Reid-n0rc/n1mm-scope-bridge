# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The website builds for this version (lane:site, #21 replaces this placeholder)."""

from __future__ import annotations

from regression_core import PENDING, Step, StepContext


def steps(ctx: StepContext) -> list[Step]:
    return [Step("Website builds for this version", disabled_reason=f"{PENDING}21")]
