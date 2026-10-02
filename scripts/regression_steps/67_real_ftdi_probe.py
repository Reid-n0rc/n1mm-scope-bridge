# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""FTDI's real LibFT4222/D2XX load, and probe reports "no radio" cleanly (#37).

Windows only: downloads FTDI's DLLs (hash-pinned, scripts/fetch_ftdi.py) into a
temporary folder that is deleted afterwards. The runner has no FT-710, so the
expected result is exit 1 with the friendly "Could not open" message.

Per architecture (#149): x64 and 32-bit x86 Python load FTDI's matching DLLs.
Native ARM64 Python has no downloadable ARM64 DLLs, so it gets the x64 ones and
must explain the mismatch instead of crashing.
"""

from __future__ import annotations

import sysconfig
import tempfile
from pathlib import Path

from regression_core import CheckFailed, Runner, Step, StepContext, run_command, tail

EXPECTED = "error: Could not open 'FT4222 A'"
MISMATCH = "error: Found FTDI DLLs built for x64"


def plan(platform: str | None = None) -> tuple[str, str]:
    """(FTDI pin architecture to fetch, expected probe output) for this Python."""
    platform = platform or sysconfig.get_platform()
    if platform == "win-arm64":
        return "amd64", MISMATCH
    if platform == "win32":
        return "i386", EXPECTED
    return "amd64", EXPECTED


def real_ftdi_probe(
    runner: Runner = run_command, workdir: Path | None = None, platform: str | None = None
) -> None:
    arch, expected = plan(platform)
    with tempfile.TemporaryDirectory() as tmp:
        dest = workdir or Path(tmp)
        fetch = (
            "uv",
            "run",
            "python",
            "scripts/fetch_ftdi.py",
            "--dest",
            str(dest),
            "--arch",
            arch,
        )
        code, out = runner(fetch)
        if code != 0:
            raise CheckFailed(f"could not fetch FTDI libraries:\n{tail(out)}")
        lib = str(dest / "lib")
        code, out = runner(("uv", "run", "n1mm-scope-bridge", "probe", "--ftdi-lib-dir", lib))
        if code != 1 or expected not in out:
            raise CheckFailed(
                f"real-DLL probe: expected exit 1 and {expected!r}, got {code}:\n{tail(out)}"
            )
        if "Traceback" in out:
            raise CheckFailed(f"probe printed a traceback:\n{tail(out)}")


def steps(ctx: StepContext) -> list[Step]:
    return [
        Step(
            "Real FTDI DLLs load; probe reports no radio",
            windows_only=True,
            action=lambda: real_ftdi_probe(ctx.runner),
        )
    ]
