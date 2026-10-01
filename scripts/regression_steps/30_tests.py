# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The whole test suite, including slow and licensing tests, with coverage."""

from __future__ import annotations

from regression_core import Step, StepContext


def steps(ctx: StepContext) -> list[Step]:
    nogui = ("--cov-config=.coveragerc-nogui",) if ctx.skip_gui else ()
    command = (
        "uv",
        "run",
        "pytest",
        "--cov",
        "--cov-report=term-missing",
        "-p",
        "no:cacheprovider",
    )
    return [Step("Unit, slow, and licensing tests with coverage", (*command, *nogui))]
