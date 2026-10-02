# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import json
import zipfile
from collections.abc import Sequence
from pathlib import Path

import pytest
from regression_core import GUI_SKIP, CheckFailed, Runner, StepContext
from stepload import fake_runner, load_step

shots = load_step("77_gui_screenshots")


def write_shots(out: Path, *, drop: str = "", tiny: str = "", no_alt: str = "") -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for scene in shots.REQUIRED:
        if scene == drop:
            continue
        (out / f"{scene}.png").write_bytes(b"\x89PNG" + (b"" if scene == tiny else b"x" * 2048))
        manifest[scene] = {"file": f"{scene}.png", "alt": "" if scene == no_alt else "alt"}
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def screenshot_runner(code: int = 0) -> Runner:
    def run(cmd: Sequence[str]) -> tuple[int, str]:
        if code == 0:
            write_shots(Path(cmd[-1]))
        return code, "done"

    return run


def test_command_uses_the_gui_cli() -> None:
    assert shots.command(Path("d")) == (
        "uv",
        "run",
        "n1mm-scope-bridge",
        "gui",
        "--screenshot",
        "d",
    )


def test_generate_checks_and_zips(tmp_path: Path) -> None:
    out, target = tmp_path / "shots", tmp_path / "screenshots.zip"
    shots.generate(screenshot_runner(), out, target)
    with zipfile.ZipFile(target) as zf:
        names = set(zf.namelist())
    assert {"manifest.json", "main-window.png", "close-prompt.png", "ftdi-error.png"} <= names


def test_generate_reports_a_failed_run(tmp_path: Path) -> None:
    with pytest.raises(CheckFailed, match="screenshot run failed"):
        shots.generate(screenshot_runner(code=1), tmp_path / "s", tmp_path / "s.zip")


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"drop": "close-prompt"}, "missing from the manifest"),
        ({"tiny": "main-window"}, "missing or empty"),
        ({"no_alt": "ftdi-error"}, "no alt text"),
    ],
)
def test_check_rejects_bad_output(tmp_path: Path, kw: dict[str, str], message: str) -> None:
    write_shots(tmp_path, **kw)
    with pytest.raises(CheckFailed, match=message):
        shots.check(tmp_path)


def test_check_without_manifest(tmp_path: Path) -> None:
    with pytest.raises(CheckFailed, match="no usable manifest"):
        shots.check(tmp_path)
    (tmp_path / "manifest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(CheckFailed, match="not an object"):
        shots.check(tmp_path)


def test_steps_and_free_threaded_skip() -> None:
    (step,) = shots.steps(StepContext(runner=fake_runner()))
    assert step.action is not None
    assert not step.windows_only
    (skipped,) = shots.steps(StepContext(runner=fake_runner(), skip_gui=True))
    assert skipped.disabled_reason == GUI_SKIP
