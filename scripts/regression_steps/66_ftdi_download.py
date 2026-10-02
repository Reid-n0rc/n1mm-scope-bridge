# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The installer's pinned FTDI download still works (#133).

Runs scripts/check_ftdi_download.py: the pinned URL answers HTTP 200 with the
pinned SHA-256, holds both DLLs, and (on Windows) both Authenticode signatures
are valid. A release can't ship with an installer whose download is dead.
"""

from __future__ import annotations

from regression_core import CheckFailed, Runner, Step, StepContext, run_command, tail

CHECK = ("uv", "run", "python", "scripts/check_ftdi_download.py")


def ftdi_download(runner: Runner = run_command) -> None:
    code, out = runner(CHECK)
    if code != 0 or "FTDI download OK" not in out:
        raise CheckFailed(f"FTDI download check failed ({code}):\n{tail(out)}")


def steps(ctx: StepContext) -> list[Step]:
    return [
        Step(
            "FTDI library download (installer pin) works", action=lambda: ftdi_download(ctx.runner)
        )
    ]
