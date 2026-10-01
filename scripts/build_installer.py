# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Build the Windows installer with Inno Setup (issue #20).

    uv run python scripts/build_installer.py [--app-dir DIR] [--iscc PATH]

Compiles packaging/windows/installer.iss around the PyInstaller one-folder
app from scripts/build_windows_app.py and writes
dist/windows/n1mm-scope-bridge-setup-<version>.exe. Refuses to build if the
app folder contains FTDI binaries or is missing the GUI exe or license files.
Standard library only; Windows only (Inno Setup is a Windows tool).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import build_windows_app as app

ROOT = app.ROOT
ISS = ROOT / "packaging" / "windows" / "installer.iss"
APP_DIR = app.OUT / app.APP_NAME
REQUIRED = (f"{app.APP_NAME}.exe", f"{app.GUI_EXE}.exe", "licenses/LICENSE", "licenses/NOTICE",
            "licenses/THIRD_PARTY.md")  # fmt: skip

Runner = Callable[[Sequence[str]], tuple[int, str]]


class InstallerError(Exception):
    pass


def run_command(cmd: Sequence[str]) -> tuple[int, str]:  # pragma: no cover
    proc = subprocess.run(
        list(cmd), cwd=ROOT, capture_output=True, text=True, check=False, errors="replace"
    )
    return proc.returncode, proc.stdout + proc.stderr


def find_iscc(explicit: str | None = None, env: dict[str, str] | None = None) -> str:
    """ISCC.exe from --iscc, $ISCC, PATH, or the default Inno Setup folders."""
    env = dict(os.environ) if env is None else env
    candidates = [explicit, env.get("ISCC"), shutil.which("ISCC.exe") or shutil.which("iscc")]
    for base in (env.get("ProgramFiles(x86)"), env.get("ProgramFiles"), env.get("LOCALAPPDATA")):
        if base:
            candidates += [str(Path(base) / f"Inno Setup {v}" / "ISCC.exe") for v in (7, 6)]
            candidates.append(str(Path(base) / "Programs" / "Inno Setup 7" / "ISCC.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise InstallerError("Inno Setup's ISCC.exe not found; install Inno Setup 7 or pass --iscc")


def check_app_dir(app_dir: Path) -> None:
    if not app_dir.is_dir():
        raise InstallerError(f"{app_dir} not found; run scripts/build_windows_app.py first")
    missing = [r for r in REQUIRED if not (app_dir / r).is_file()]
    if missing:
        raise InstallerError(f"app folder is missing: {', '.join(missing)}")
    bad = app.find_forbidden(str(p.relative_to(app_dir)) for p in app_dir.rglob("*"))
    if bad:
        raise InstallerError(f"FTDI binaries must never be bundled: {bad}")


def iscc_command(iscc: str, version: str, app_dir: Path, out_dir: Path) -> list[str]:
    return [iscc, "/Q", f"/DAppVersion={version}", f"/DSourceDir={app_dir}",
            f"/DOutputDir={out_dir}", str(ISS)]  # fmt: skip


def installer_name(version: str) -> str:
    return f"n1mm-scope-bridge-setup-{version}.exe"


def build(app_dir: Path, iscc: str, runner: Runner = run_command) -> Path:
    check_app_dir(app_dir)
    version = app.read_version()
    out_dir = app_dir.parent
    code, log = runner(iscc_command(iscc, version, app_dir, out_dir))
    if code != 0:
        raise InstallerError(f"ISCC failed ({code}):\n{log[-4000:]}")
    installer = out_dir / installer_name(version)
    if not installer.is_file():
        raise InstallerError(f"ISCC did not produce {installer.name}")
    return installer


def main(argv: Sequence[str] | None = None, *, runner: Runner = run_command) -> int:
    parser = argparse.ArgumentParser(description="Build the Windows installer (Inno Setup).")
    parser.add_argument("--app-dir", type=Path, default=APP_DIR)
    parser.add_argument("--iscc", help="path to ISCC.exe")
    args = parser.parse_args(argv)
    try:
        installer = build(args.app_dir, find_iscc(args.iscc), runner)
    except InstallerError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(f"built {installer}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
