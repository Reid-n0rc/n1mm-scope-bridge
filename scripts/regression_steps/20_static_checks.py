# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Lint, format, and strict type checks."""

from __future__ import annotations

from regression_core import Step, StepContext

GUI_PATHS = r"(src/n1mm_scope_bridge/gui/|tests/test_gui)"


def steps(ctx: StepContext) -> list[Step]:
    # Without PySide6 the GUI can't be type-checked; the 3.13 jobs check it.
    mypy_gui = ("--exclude", GUI_PATHS) if ctx.skip_gui else ()
    return [
        Step("Lint (ruff)", ("uv", "run", "ruff", "check", ".")),
        Step("Format (ruff)", ("uv", "run", "ruff", "format", "--check", ".")),
        Step("Type check (mypy --strict)", ("uv", "run", "mypy", *mypy_gui)),
    ]
