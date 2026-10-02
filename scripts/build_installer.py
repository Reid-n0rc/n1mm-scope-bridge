# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Build the Windows installer with Inno Setup (issue #20).

    uv run python scripts/build_installer.py [--app-dir DIR] [--app-arm64 DIR]
        [--app-x86 DIR] [--require-all] [--iscc PATH]

Compiles packaging/windows/installer.iss into ONE installer for all Windows
PCs (#149): the x64 app (--app-dir), the native ARM64 app (--app-arm64) and
the 32-bit command-line app (--app-x86), each from scripts/build_windows_app.py
on its own architecture. Setup picks the payload at install time. Writes
dist/windows/n1mm-scope-bridge-setup-<version>.exe. Refuses to build if an
app folder contains FTDI binaries or is missing its exes or license files.
Releases pass --require-all; development builds may include any subset.
Standard library only; Windows only (Inno Setup is a Windows tool).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import build_windows_app as app
import fetch_ftdi
import ftdi_driver

ROOT = app.ROOT
ISS = ROOT / "packaging" / "windows" / "installer.iss"
APP_DIR = app.OUT / app.APP_NAME
LICENSES = ("licenses/LICENSE", "licenses/NOTICE", "licenses/THIRD_PARTY.md")
REQUIRED = (f"{app.APP_NAME}.exe", f"{app.GUI_EXE}.exe", *LICENSES)
REQUIRED_CLI_ONLY = (f"{app.APP_NAME}.exe", *LICENSES)
"""The 32-bit x86 payload is the command-line app only (no Qt 6 on 32-bit Windows)."""
PAYLOADS = (("x64", "SourceX64"), ("arm64", "SourceArm64"), ("x86", "SourceX86"))
"""(payload name, ISCC define) in installer.iss's order."""
LOCAL_PAYLOAD = {"x64": "x64", "ARM64": "arm64", "x86": "x86"}

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


def check_app_dir(app_dir: Path, required: Sequence[str] = REQUIRED) -> None:
    if not app_dir.is_dir():
        raise InstallerError(f"{app_dir} not found; run scripts/build_windows_app.py first")
    missing = [r for r in required if not (app_dir / r).is_file()]
    if missing:
        raise InstallerError(f"app folder is missing: {', '.join(missing)}")
    bad = app.find_forbidden(str(p.relative_to(app_dir)) for p in app_dir.rglob("*"))
    if bad:
        raise InstallerError(f"FTDI binaries must never be bundled: {bad}")


def ftdi_defines(pin: Path = fetch_ftdi.PIN, *, i386: bool = False) -> list[str]:
    """/D defines for the installer's FTDI download, from the single pin (#133, #149).

    The amd64 pin serves the x64 payload (also on Windows on ARM, emulated);
    the i386 pin serves the 32-bit payload. There is no ARM64 pin.
    """
    pkg, signers = fetch_ftdi.load_pin(pin)
    data = json.loads(pin.read_text(encoding="utf-8"))
    defines = [
        f"/DFtdiWheelUrl={pkg.url}",
        f"/DFtdiWheelSha256={pkg.sha256}",
        f"/DFtdiWheelFile={pkg.filename}",
        f"/DFtdiLibSigner={signers['LibFT4222-64.dll']}",
        f"/DFtdiD2xxSigner={signers['ftd2xx.dll']}",
        f"/DFtdiLicenceUrl={data['licence_url']}",
    ]
    if i386:
        pkg86, signers86 = fetch_ftdi.load_pin(pin, "i386")
        defines += [
            f"/DFtdiWheelUrl86={pkg86.url}",
            f"/DFtdiWheelSha25686={pkg86.sha256}",
            f"/DFtdiWheelFile86={pkg86.filename}",
            f"/DFtdiLibSigner86={signers86['LibFT4222.dll']}",
            f"/DFtdiD2xxSigner86={signers86['ftd2xx.dll']}",
        ]
    return defines


def iscc_command(iscc: str, version: str, apps: dict[str, Path], out_dir: Path) -> list[str]:
    """``apps`` maps payload name (x64, arm64, x86) to its one-folder app."""
    # Absolute paths: ISCC resolves relative ones against the .iss folder.
    sources = [f"/D{define}={apps[name].absolute()}" for name, define in PAYLOADS if name in apps]
    return [iscc, "/Q", f"/DAppVersion={version}", *sources, f"/DOutputDir={out_dir}",
            *ftdi_defines(i386="x86" in apps), *ftdi_driver.installer_defines(),
            str(ISS)]  # fmt: skip


def installer_name(version: str) -> str:
    return f"n1mm-scope-bridge-setup-{version}.exe"


def build(
    apps: dict[str, Path],
    iscc: str,
    runner: Runner = run_command,
    *,
    require_all: bool = False,
    out_dir: Path | None = None,
) -> Path:
    """Build the installer into ``out_dir`` (default: the first app folder's parent)."""
    if not apps:
        raise InstallerError("no app folders given")
    unknown = sorted(set(apps) - {name for name, _ in PAYLOADS})
    if unknown:
        raise InstallerError(f"unknown payload(s): {', '.join(unknown)}")
    if require_all:
        missing = [name for name, _ in PAYLOADS if name not in apps]
        if missing:
            raise InstallerError(f"a release installer needs every payload; missing: {missing}")
    for name, app_dir in apps.items():
        check_app_dir(app_dir, REQUIRED_CLI_ONLY if name == "x86" else REQUIRED)
    version = app.read_version()
    if out_dir is None:
        out_dir = apps["x64"].parent if "x64" in apps else next(iter(apps.values())).parent
    out_dir = out_dir.absolute()  # ISCC resolves relative paths against the .iss folder
    out_dir.mkdir(parents=True, exist_ok=True)
    code, log = runner(iscc_command(iscc, version, apps, out_dir))
    if code != 0:
        raise InstallerError(f"ISCC failed ({code}):\n{log[-4000:]}")
    installer = out_dir / installer_name(version)
    if not installer.is_file():
        raise InstallerError(f"ISCC did not produce {installer.name}")
    return installer


def main(argv: Sequence[str] | None = None, *, runner: Runner = run_command) -> int:
    parser = argparse.ArgumentParser(description="Build the Windows installer (Inno Setup).")
    parser.add_argument("--app-dir", type=Path, help="x64 app folder (default: dist/windows)")
    parser.add_argument("--app-arm64", type=Path, help="native ARM64 app folder")
    parser.add_argument("--app-x86", type=Path, help="32-bit command-line app folder")
    parser.add_argument("--require-all", action="store_true", help="release: all three payloads")
    parser.add_argument("--iscc", help="path to ISCC.exe")
    args = parser.parse_args(argv)
    apps: dict[str, Path] = {}
    if args.app_dir:
        apps["x64"] = args.app_dir
    elif not (args.app_arm64 or args.app_x86):
        # Development / regression: the app this machine just built, as its own payload.
        apps[LOCAL_PAYLOAD[app.build_arch()]] = APP_DIR
    if args.app_arm64:
        apps["arm64"] = args.app_arm64
    if args.app_x86:
        apps["x86"] = args.app_x86
    try:
        installer = build(
            apps, find_iscc(args.iscc), runner, require_all=args.require_all, out_dir=app.OUT
        )
    except InstallerError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(f"built {installer} with payloads: {', '.join(apps)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
