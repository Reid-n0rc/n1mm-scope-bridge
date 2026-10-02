# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Build the Windows application with PyInstaller (issue #6).

    uv run --group packaging python scripts/build_windows_app.py

Steps: write the Windows version resource, run PyInstaller on
packaging/windows/n1mm_scope_bridge.spec (one-folder), copy the license
files into the app, refuse FTDI binaries, smoke-test the built CLI (legal
notices, then emulator frames into a UDP listener), and zip the result as
dist/windows/n1mm-scope-bridge-<version>-<arch>.zip, where <arch> is win64
(x64), winarm64 (native ARM64) or win32 (32-bit x86, command line only:
Qt 6 has no 32-bit Windows build) for the Python that runs the build (#149).

Standard library only. Windows is the product platform; on other systems the
same steps build a native app for development (with --allow-non-windows).
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import socket
import subprocess
import sys
import sysconfig
import zipfile
from collections.abc import Callable, Iterable, Sequence
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "windows" / "n1mm_scope_bridge.spec"
GUI_MODULE = ROOT / "src" / "n1mm_scope_bridge" / "gui" / "app.py"
OUT = ROOT / "dist" / "windows"
WORK = ROOT / "build" / "pyinstaller"
APP_NAME = "n1mm-scope-bridge"
GUI_EXE = "N1MM Scope Bridge"
LICENSE_FILES = ("LICENSE", "NOTICE", "THIRD_PARTY.md")
FORBIDDEN = ("*ft4222*.dll", "*ft4222*.so*", "*ft4222*.dylib", "*ftd2xx*")
QT_DISTRIBUTIONS = ("PySide6-Essentials", "PySide6_Essentials", "shiboken6")
MIN_PACKETS = 3
COMMAND_TIMEOUT_S = 900  # PyInstaller can be slow; the app checks finish in seconds

Runner = Callable[[Sequence[str], dict[str, str] | None], tuple[int, str]]


class BuildError(Exception):
    """A build step failed; the message says which and why."""


def run_command(
    cmd: Sequence[str], env: dict[str, str] | None = None
) -> tuple[int, str]:  # pragma: no cover
    try:
        proc = subprocess.run(
            list(cmd), cwd=ROOT, env=env, capture_output=True, text=True, check=False,
            errors="replace", timeout=COMMAND_TIMEOUT_S,
        )  # fmt: skip
    except subprocess.TimeoutExpired as err:
        partial = (err.stdout or b"") + (err.stderr or b"")
        text = partial.decode(errors="replace") if isinstance(partial, bytes) else str(partial)
        return 124, f"timed out after {COMMAND_TIMEOUT_S} s\n{text}"
    return proc.returncode, proc.stdout + proc.stderr


def read_version(init: Path = ROOT / "src" / "n1mm_scope_bridge" / "__init__.py") -> str:
    match = re.search(r'^__version__ = "([^"]+)"', init.read_text(encoding="utf-8"), re.M)
    if not match:
        raise BuildError(f"no __version__ in {init}")
    return match.group(1)


def version_tuple(version: str) -> tuple[int, int, int, int]:
    """Windows needs four integers: '1.2.3rc1' -> (1, 2, 3, 0)."""
    match = re.match(r"\d+(?:\.\d+)*", version)
    numbers = [int(n) for n in match.group(0).split(".")][:4] if match else []
    if not numbers:
        raise BuildError(f"cannot make a Windows version from {version!r}")
    return (*numbers, 0, 0, 0, 0)[:4]  # type: ignore[return-value]


def version_info_text(version: str) -> str:
    """PyInstaller version-resource file (a Python literal it evaluates)."""
    v = version_tuple(version)
    strings = {
        "CompanyName": "Reid Crowe, N0RC",
        "FileDescription": "N1MM Scope Bridge: radio spectrum scope to N1MM Logger+",
        "FileVersion": version,
        "InternalName": APP_NAME,
        "LegalCopyright": "Copyright (C) 2026 Reid Crowe, N0RC. GPL-3.0-only.",
        "OriginalFilename": f"{APP_NAME}.exe",
        "ProductName": "N1MM Scope Bridge",
        "ProductVersion": version,
    }
    entries = ",\n          ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings.items())
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
          {entries}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def find_forbidden(paths: Iterable[str]) -> list[str]:
    """FTDI binaries that must never ship (GPL; users install them from FTDI)."""
    return sorted(
        p for p in paths for pat in FORBIDDEN if fnmatch.fnmatch(Path(p).name.lower(), pat)
    )


def qt_license_files() -> list[Path]:  # pragma: no cover - depends on installed PySide6
    found: list[Path] = []
    for name in QT_DISTRIBUTIONS:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        for f in dist.files or []:
            if re.search(r"(LICENSE|COPYING|NOTICE)", Path(str(f)).name, re.I):
                found.append(Path(str(dist.locate_file(f))))
    return found


def collect_licenses(
    app_dir: Path, *, qt_files: Sequence[Path] = (), root: Path = ROOT
) -> list[Path]:
    """Copy this project's license files (and Qt's, if bundled) into app_dir/licenses."""
    dest = app_dir / "licenses"
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in LICENSE_FILES:
        src = root / name
        if not src.is_file():
            raise BuildError(f"missing {name}")
        copied.append(Path(shutil.copy2(src, dest / name)))
    if qt_files:
        (dest / "qt").mkdir(exist_ok=True)
        for src in qt_files:
            copied.append(Path(shutil.copy2(src, dest / "qt" / f"{src.parent.name}-{src.name}")))
    return copied


ARCH_SUFFIX = {"x64": "win64", "ARM64": "winarm64", "x86": "win32"}
"""Zip-name suffix for each Windows architecture of the built app (#149)."""


def build_arch(platform_tag: str | None = None) -> str:
    """Architecture of the Python running the build: "x64", "ARM64" or "x86".

    PyInstaller freezes that interpreter, so this is the app's architecture.
    Mirrors ``n1mm_scope_bridge.transport.ft4222.process_arch``.
    """
    tag = (platform_tag or sysconfig.get_platform()).lower()
    if tag.endswith("arm64"):
        return "ARM64"
    if tag.endswith(("amd64", "x86_64")):
        return "x64"
    return "x86"


def zip_name(version: str, arch: str = "x64") -> str:
    return f"{APP_NAME}-{version}-{ARCH_SUFFIX[arch]}.zip"


def make_zip(app_dir: Path, out: Path) -> Path:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(app_dir.rglob("*")):
            if path.is_file():
                zf.write(path, Path(app_dir.name) / path.relative_to(app_dir))
    return out


def exe_path(app_dir: Path, name: str = APP_NAME, windows: bool = sys.platform == "win32") -> Path:
    return app_dir / (f"{name}.exe" if windows else name)


def gui_self_test(gui: Path, runner: Runner = run_command) -> None:
    """The built windowed GUI streams the emulator through its real window.

    QT_DEBUG_PLUGINS makes Qt explain a missing platform plugin instead of
    failing silently (in a frozen app that shows a modal error box).
    """
    env = {**os.environ, "QT_DEBUG_PLUGINS": "1"}
    code, out = runner((str(gui), "--self-test"), env)
    if code != 0:
        raise BuildError(f"{gui.name} --self-test failed ({code}):\n{out[-4000:]}")


def smoke_test(cli: Path, runner: Runner = run_command) -> None:
    """The built CLI shows its legal notices and streams emulator frames to UDP."""
    code, out = runner((str(cli), "--version"), None)
    if code != 0 or "ABSOLUTELY NO WARRANTY" not in out:
        raise BuildError(f"{cli.name} --version failed ({code}):\n{out[-2000:]}")
    code, out = runner((str(cli), "--license"), None)
    if code != 0 or "corresponding source" not in out:
        raise BuildError(f"{cli.name} --license failed ({code}):\n{out[-2000:]}")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 21)
        rx.bind(("127.0.0.1", 0))
        port = str(rx.getsockname()[1])
        cmd = (str(cli), "run", "--emulator", "--duration", "2", "--rate", "10", "--port", port)
        code, out = runner(cmd, None)
        rx.settimeout(0.5)
        packets = []
        while True:
            try:
                packets.append(rx.recv(65535))
            except OSError:
                break
    if code != 0:
        raise BuildError(f"{cli.name} run --emulator failed ({code}):\n{out[-2000:]}")
    if len(packets) < MIN_PACKETS:
        raise BuildError(f"{cli.name} sent {len(packets)} packets, expected >= {MIN_PACKETS}")
    # Our own app on loopback: a byte check is enough (no XML parser needed).
    for data in packets:
        if not (data.startswith(b"<?xml") and b"<Spectrum>" in data and b"</Spectrum>" in data):
            raise BuildError("the built app sent a packet that is not <Spectrum>")


def build(
    *,
    gui: bool,
    arch: str = "x64",
    out: Path = OUT,
    work: Path = WORK,
    smoke: bool = True,
    runner: Runner = run_command,
    qt_files: Callable[[], Sequence[Path]] = qt_license_files,
) -> Path:
    version = read_version()
    shutil.rmtree(out, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    version_file = work / "version_info.txt"
    version_file.write_text(version_info_text(version), encoding="utf-8")
    env = {
        **os.environ,
        "N1MM_BUILD_GUI": "1" if gui else "0",
        "N1MM_VERSION_FILE": str(version_file),
    }
    cmd = ("pyinstaller", "--noconfirm", "--clean", "--distpath", str(out),
           "--workpath", str(work), str(SPEC))  # fmt: skip
    code, log = runner(cmd, env)
    if code != 0:
        raise BuildError(f"PyInstaller failed ({code}):\n{log[-4000:]}")
    app_dir = out / APP_NAME
    collect_licenses(app_dir, qt_files=qt_files() if gui else ())
    bad = find_forbidden(str(p.relative_to(app_dir)) for p in app_dir.rglob("*"))
    if bad:
        raise BuildError(f"FTDI binaries must never be bundled: {bad}")
    if gui and not exe_path(app_dir, GUI_EXE).exists():
        raise BuildError(f"{GUI_EXE} was not built")
    if smoke:
        smoke_test(exe_path(app_dir), runner)
        if gui:
            gui_self_test(exe_path(app_dir, GUI_EXE), runner)
    return make_zip(app_dir, out / zip_name(version, arch))


def main(argv: Sequence[str] | None = None, *, runner: Runner = run_command) -> int:
    parser = argparse.ArgumentParser(description="Build the Windows app (PyInstaller, one-folder).")
    parser.add_argument(
        "--gui",
        choices=("auto", "on", "off"),
        default="auto",
        help="build the windowed GUI exe (auto: if n1mm_scope_bridge.gui.app exists)",
    )
    parser.add_argument("--no-smoke", action="store_true", help="skip running the built app")
    parser.add_argument(
        "--allow-non-windows", action="store_true", help="development builds on macOS/Linux"
    )
    args = parser.parse_args(argv)
    if sys.platform != "win32" and not args.allow_non_windows:
        print(
            "error: build on Windows, or pass --allow-non-windows for a dev build", file=sys.stderr
        )
        return 2
    arch = build_arch()
    gui = args.gui == "on" or (args.gui == "auto" and GUI_MODULE.exists())
    if arch == "x86" and gui:
        if args.gui == "on":
            print("error: the GUI needs 64-bit Windows (Qt 6 has no 32-bit build)", file=sys.stderr)
            return 2
        gui = False  # 32-bit x86: command-line app only
    try:
        zipped = build(gui=gui, arch=arch, smoke=not args.no_smoke, runner=runner)
    except BuildError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(f"built {zipped} for {arch} (GUI exe: {'yes' if gui else 'no'})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
