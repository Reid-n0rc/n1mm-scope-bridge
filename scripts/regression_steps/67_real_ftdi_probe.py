# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""FTDI's real LibFT4222/D2XX load, and probe reports "no radio" cleanly (#37).

Windows only: downloads FTDI's DLLs (hash-pinned, scripts/fetch_ftdi.py) into a
temporary folder that is deleted afterwards. The runner has no FT-710, so the
expected result is exit 1 with the friendly "Could not open" message.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from regression_core import CheckFailed, Runner, Step, StepContext, run_command, tail

EXPECTED = "error: Could not open 'FT4222 A'"


def real_ftdi_probe(runner: Runner = run_command, workdir: Path | None = None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        dest = workdir or Path(tmp)
        code, out = runner(("uv", "run", "python", "scripts/fetch_ftdi.py", "--dest", str(dest)))
        if code != 0:
            raise CheckFailed(f"could not fetch FTDI libraries:\n{tail(out)}")
        lib = str(dest / "lib")
        code, out = runner(("uv", "run", "n1mm-scope-bridge", "probe", "--ftdi-lib-dir", lib))
        if code != 1 or EXPECTED not in out:
            raise CheckFailed(
                f"real-DLL probe: expected exit 1 and {EXPECTED!r}, got {code}:\n{tail(out)}"
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
