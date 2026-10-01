# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Git and agent hook tests."""

from __future__ import annotations

import shutil

from regression_core import Step, StepContext


def steps(ctx: StepContext) -> list[Step]:
    return [Step("Git and agent hook tests", (shutil.which("sh") or "sh", "tests/hooks/run.sh"))]
