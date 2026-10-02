# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Build the PyInstaller Windows app and run it (#6).

scripts/build_windows_app.py builds the one-folder app, refuses FTDI
binaries, and smoke-tests the frozen executables: CLI legal notices, emulator
frames into a UDP listener, and (when bundled) the GUI --self-test. Free-
threaded jobs (--skip-gui) build the CLI only, since PySide6 is unavailable.
"""

from __future__ import annotations

from regression_core import Step, StepContext


def command(skip_gui: bool) -> tuple[str, ...]:
    return ("uv", "run", "--group", "packaging", "python", "scripts/build_windows_app.py",
            "--gui", "off" if skip_gui else "auto")  # fmt: skip


def steps(ctx: StepContext) -> list[Step]:
    return [Step("Windows app (PyInstaller) runs", command(ctx.skip_gui), windows_only=True)]
