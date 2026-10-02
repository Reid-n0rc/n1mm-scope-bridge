# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The website builds for this version, with this build's screenshots (#21, #68).

Uses the screenshots from step 77 when they exist (they don't on --skip-gui
jobs) and fails on broken links, missing anchors, or images without alt text
or size.
"""

from __future__ import annotations

from pathlib import Path

from regression_core import DIST, CheckFailed, Runner, Step, StepContext, tail

SHOTS = DIST / "screenshots"
OUT = DIST / "site"


def command(shots: Path = SHOTS, out: Path = OUT) -> tuple[str, ...]:
    cmd: tuple[str, ...] = (
        "uv", "run", "--no-project", "python", "scripts/build_site.py", "--out", str(out),
    )  # fmt: skip
    if (shots / "manifest.json").is_file():
        cmd += ("--screenshots", str(shots))
    return cmd


def build(runner: Runner, shots: Path = SHOTS, out: Path = OUT) -> None:
    code, output = runner(command(shots, out))
    if code != 0:
        raise CheckFailed(f"site build failed ({code}):\n{tail(output)}")


def steps(ctx: StepContext) -> list[Step]:
    return [Step("Website builds for this version", action=lambda: build(ctx.runner))]
