# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Build the installer and run its silent install/run/uninstall smoke test (#20).

Needs the app from 70_windows_app (with the GUI) and Inno Setup's ISCC.exe
(found via $ISCC, PATH, or the default install folders; the Release
regression workflow installs a pinned copy). The local build holds only this
runner's architecture, so the smoke test forces that payload (#149); the
all-architecture installer is tested by the Windows installer workflow.
"""

from __future__ import annotations

import sysconfig

from regression_core import GUI_SKIP, ROOT, CheckFailed, Runner, Step, StepContext, tail

SMOKE = ROOT / "packaging" / "windows" / "smoke_test.ps1"
INSTALLER_GLOB = "n1mm-scope-bridge-setup-*.exe"
PAYLOADS = {"win-amd64": "x64", "win-arm64": "arm64", "win32": "x86"}


def local_payload(platform: str | None = None) -> str:
    return PAYLOADS.get(platform or sysconfig.get_platform(), "x64")


def installer_smoke(runner: Runner, platform: str | None = None) -> None:
    code, out = runner(("uv", "run", "--no-project", "python", "scripts/build_installer.py"))
    if code != 0:
        raise CheckFailed(f"installer build failed ({code}):\n{tail(out)}")
    installers = sorted((ROOT / "dist" / "windows").glob(INSTALLER_GLOB))
    if len(installers) != 1:
        raise CheckFailed(f"expected one installer in dist/windows, found {len(installers)}")
    cmd = ("pwsh", "-NoProfile", "-File", str(SMOKE), "-Installer", str(installers[0]),
           "-Payload", local_payload(platform))  # fmt: skip
    code, out = runner(cmd)
    if code != 0:
        raise CheckFailed(f"installer smoke test failed ({code}):\n{tail(out)}")


def steps(ctx: StepContext) -> list[Step]:
    name = "Installer silent install/run/uninstall"
    if ctx.skip_gui:
        return [Step(name, windows_only=True, disabled_reason=GUI_SKIP)]
    return [Step(name, action=lambda: installer_smoke(ctx.runner), windows_only=True)]
