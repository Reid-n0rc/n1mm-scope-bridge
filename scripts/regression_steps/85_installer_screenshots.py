# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Installer wizard screenshots for the website (#22).

Runs after 77_gui_screenshots and 80_installer: walks the built installer's
wizard on the Windows desktop (packaging/windows/installer_screenshots.ps1),
then merges the pages into the same screenshot set and rebuilds
``dist/regression/screenshots.zip``, the release asset the website uses.
"""

from __future__ import annotations

import json
import shutil
import sysconfig
import zipfile
from pathlib import Path

from regression_core import DIST, GUI_SKIP, ROOT, CheckFailed, Runner, Step, StepContext, tail

ARM_SKIP = (
    "website screenshots come from the x64 job; the wizard walk can't click past the "
    "licence page on the windows-11-arm runner (#149)"
)
SCRIPT = ROOT / "packaging" / "windows" / "installer_screenshots.ps1"
INSTALLERS = ROOT / "dist" / "windows"
INSTALLER_GLOB = "n1mm-scope-bridge-setup-*.exe"
RAW = DIST / "installer-screenshots"
SHOTS = DIST / "screenshots"
ZIP = DIST / "screenshots.zip"
REQUIRED = (
    "installer-license",
    "installer-tasks",
    "installer-finished",
)  # FTDI page: only when the download is off (#133)


def command(installer: Path, out: Path = RAW) -> tuple[str, ...]:
    return (
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
        "-Installer", str(installer), "-OutDir", str(out),
    )  # fmt: skip


def read_manifest(folder: Path) -> dict[str, dict[str, object]]:
    try:
        data = json.loads((folder / "manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as err:
        raise CheckFailed(f"no usable manifest.json in {folder}: {err}") from None
    if not isinstance(data, dict):
        raise CheckFailed(f"manifest.json in {folder} is not an object")
    return data


def check(raw: Path = RAW) -> dict[str, dict[str, object]]:
    """Every required wizard page was captured, with alt text and a real image."""
    manifest = read_manifest(raw)
    for scene in REQUIRED:
        entry = manifest.get(scene)
        if not isinstance(entry, dict):
            raise CheckFailed(f"installer screenshot {scene!r} was not captured")
        png = raw / str(entry.get("file", ""))
        if not png.is_file() or png.stat().st_size < 1024:
            raise CheckFailed(f"installer screenshot {png.name} is missing or empty")
        if not entry.get("alt") or not entry.get("caption"):
            raise CheckFailed(f"installer screenshot {scene!r} has no alt text or caption")
    return manifest


def merge(raw: Path = RAW, shots: Path = SHOTS, target: Path = ZIP) -> Path:
    """Add the installer pages to the GUI screenshot set and rebuild the zip."""
    installer = check(raw)
    combined = read_manifest(shots) if (shots / "manifest.json").exists() else {}
    shots.mkdir(parents=True, exist_ok=True)
    for scene, entry in installer.items():
        shutil.copy2(raw / str(entry["file"]), shots / str(entry["file"]))
        combined[scene] = entry
    (shots / "manifest.json").write_text(json.dumps(combined, indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(shots.iterdir()):
            zf.write(path, path.name)
    return target


def generate(runner: Runner, installers: Path = INSTALLERS, raw: Path = RAW) -> None:
    found = sorted(installers.glob(INSTALLER_GLOB))
    if len(found) != 1:
        raise CheckFailed(f"expected one installer in {installers}, found {len(found)}")
    shutil.rmtree(raw, ignore_errors=True)
    code, out = runner(command(found[0], raw))
    if code != 0:
        raise CheckFailed(f"installer screenshot run failed ({code}):\n{tail(out)}")
    merge(raw, SHOTS, ZIP)  # module globals at call time (patchable in tests)


def steps(ctx: StepContext, platform: str | None = None) -> list[Step]:
    name = "Installer screenshots for the website"
    if ctx.skip_gui:
        return [Step(name, windows_only=True, disabled_reason=GUI_SKIP)]
    if platform is None:
        platform = sysconfig.get_platform()
    if platform == "win-arm64":
        return [Step(name, windows_only=True, disabled_reason=ARM_SKIP)]
    return [Step(name, action=lambda: generate(ctx.runner), windows_only=True)]
