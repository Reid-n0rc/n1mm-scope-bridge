# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""GUI screenshots for the website (#68, part of #22).

Generates the screenshots from this exact build and zips them as
``dist/regression/screenshots.zip``. The release workflow keeps it as the run
artifact ``screenshots-<tag>`` (releases carry only the installer); the Pages
build (pages.yml) uses it for the published site.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from regression_core import DIST, GUI_SKIP, CheckFailed, Runner, Step, StepContext, tail

SHOTS = DIST / "screenshots"
ZIP = DIST / "screenshots.zip"
REQUIRED = ("main-window", "close-prompt", "ftdi-error")


def command(out: Path = SHOTS) -> tuple[str, ...]:
    return ("uv", "run", "n1mm-scope-bridge", "gui", "--screenshot", str(out))


def check(out: Path = SHOTS) -> dict[str, dict[str, object]]:
    """The manifest lists every required scene, and each PNG exists and is not empty."""
    try:
        data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise CheckFailed(f"no usable manifest.json in {out}: {err}") from None
    if not isinstance(data, dict):
        raise CheckFailed(f"manifest.json in {out} is not an object")
    manifest: dict[str, dict[str, object]] = data
    for scene in REQUIRED:
        entry = manifest.get(scene)
        if not isinstance(entry, dict):
            raise CheckFailed(f"screenshot {scene!r} missing from the manifest")
        png = out / str(entry.get("file", ""))
        if not png.is_file() or png.stat().st_size < 1024:
            raise CheckFailed(f"screenshot {png.name} is missing or empty")
        if not entry.get("alt"):
            raise CheckFailed(f"screenshot {scene!r} has no alt text")
    return manifest


def make_zip(out: Path = SHOTS, target: Path = ZIP) -> Path:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(out.iterdir()):
            zf.write(path, path.name)
    return target


def generate(runner: Runner, out: Path = SHOTS, target: Path = ZIP) -> None:
    shutil.rmtree(out, ignore_errors=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    code, output = runner(command(out))
    if code != 0:
        raise CheckFailed(f"screenshot run failed ({code}):\n{tail(output)}")
    check(out)
    make_zip(out, target)


def steps(ctx: StepContext) -> list[Step]:
    name = "GUI screenshots for the website"
    if ctx.skip_gui:
        return [Step(name, command(), disabled_reason=GUI_SKIP)]
    return [Step(name, command(), action=lambda: generate(ctx.runner))]
