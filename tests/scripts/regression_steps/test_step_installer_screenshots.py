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

step = load_step("85_installer_screenshots")


def write_pages(
    out: Path, *, drop: str = "", tiny: str = "", no_alt: str = "", bom: bool = False
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for scene in (*step.REQUIRED, "installer-ready"):
        if scene == drop:
            continue
        (out / f"{scene}.png").write_bytes(b"\x89PNG" + (b"" if scene == tiny else b"x" * 2048))
        manifest[scene] = {
            "file": f"{scene}.png",
            "alt": "" if scene == no_alt else "alt text",
            "caption": "caption",
            "width": 500,
            "height": 390,
        }
    text = json.dumps(manifest)
    (out / "manifest.json").write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode())


def ps_runner(code: int = 0) -> Runner:
    def run(cmd: Sequence[str]) -> tuple[int, str]:
        if code == 0:
            write_pages(Path(cmd[cmd.index("-OutDir") + 1]))
        return code, "captured"

    return run


def test_command_runs_the_powershell_script() -> None:
    cmd = step.command(Path("setup.exe"), Path("out"))
    assert cmd[0] == "powershell"
    assert str(step.SCRIPT) in cmd
    assert cmd[cmd.index("-Installer") + 1] == "setup.exe"
    assert cmd[cmd.index("-OutDir") + 1] == "out"


def test_check_accepts_a_bom_manifest(tmp_path: Path) -> None:
    write_pages(tmp_path, bom=True)
    assert set(step.REQUIRED) <= set(step.check(tmp_path))


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"drop": "installer-finished"}, "was not captured"),
        ({"tiny": "installer-license"}, "missing or empty"),
        ({"no_alt": "installer-tasks"}, "no alt text"),
    ],
)
def test_check_failures(tmp_path: Path, kw: dict[str, str], message: str) -> None:
    write_pages(tmp_path, **kw)  # type: ignore[arg-type]
    with pytest.raises(CheckFailed, match=message):
        step.check(tmp_path)


@pytest.mark.parametrize("content", ["not json", "[1]"])
def test_bad_manifest(tmp_path: Path, content: str) -> None:
    (tmp_path / "manifest.json").write_text(content, encoding="utf-8")
    with pytest.raises(CheckFailed, match="manifest"):
        step.read_manifest(tmp_path)


def test_merge_adds_pages_to_the_gui_set_and_zip(tmp_path: Path) -> None:
    raw, shots, target = tmp_path / "raw", tmp_path / "shots", tmp_path / "s.zip"
    write_pages(raw)
    shots.mkdir()
    (shots / "main-window.png").write_bytes(b"png")
    (shots / "manifest.json").write_text(json.dumps({"main-window": {"file": "main-window.png"}}))
    step.merge(raw, shots, target)
    manifest = json.loads((shots / "manifest.json").read_text(encoding="utf-8"))
    assert {"main-window", *step.REQUIRED} <= set(manifest)
    with zipfile.ZipFile(target) as zf:
        assert {"main-window.png", "installer-tasks.png", "manifest.json"} <= set(zf.namelist())


def test_merge_without_gui_shots(tmp_path: Path) -> None:
    raw, shots = tmp_path / "raw", tmp_path / "shots"
    write_pages(raw)
    step.merge(raw, shots, tmp_path / "s.zip")
    assert set(step.REQUIRED) <= set(json.loads((shots / "manifest.json").read_text()))


def test_generate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installers = tmp_path / "dist"
    installers.mkdir()
    (installers / "n1mm-scope-bridge-setup-0.1.0.exe").write_bytes(b"MZ")
    monkeypatch.setattr(step, "SHOTS", tmp_path / "shots")
    monkeypatch.setattr(step, "ZIP", tmp_path / "s.zip")
    step.generate(ps_runner(), installers, tmp_path / "raw")
    assert (tmp_path / "s.zip").is_file()
    assert (tmp_path / "shots" / "installer-tasks.png").is_file()


def test_generate_failures(tmp_path: Path) -> None:
    with pytest.raises(CheckFailed, match="expected one installer"):
        step.generate(ps_runner(), tmp_path, tmp_path / "raw")
    (tmp_path / "n1mm-scope-bridge-setup-0.1.0.exe").write_bytes(b"MZ")
    with pytest.raises(CheckFailed, match="screenshot run failed"):
        step.generate(ps_runner(code=1), tmp_path, tmp_path / "raw")


@pytest.mark.parametrize("skip_gui", [True, False])
def test_steps(skip_gui: bool) -> None:
    (only,) = step.steps(StepContext(runner=fake_runner(), skip_gui=skip_gui))
    assert only.windows_only
    assert (only.disabled_reason == GUI_SKIP) is skip_gui
