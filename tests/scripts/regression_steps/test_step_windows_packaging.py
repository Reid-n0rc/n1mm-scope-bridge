# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from regression_core import GUI_SKIP, CheckFailed, StepContext
from stepload import fake_runner, load_step

app_step = load_step("70_windows_app")
inst_step = load_step("80_installer")


@pytest.mark.parametrize(("skip_gui", "gui"), [(False, "auto"), (True, "off")])
def test_windows_app_step(skip_gui: bool, gui: str) -> None:
    (step,) = app_step.steps(StepContext(runner=fake_runner(), skip_gui=skip_gui))
    assert step.windows_only
    assert not step.disabled_reason
    assert step.command[-2:] == ("--gui", gui)
    assert "scripts/build_windows_app.py" in step.command


def test_installer_step_skipped_without_gui() -> None:
    (step,) = inst_step.steps(StepContext(runner=fake_runner(), skip_gui=True))
    assert step.disabled_reason == GUI_SKIP


def scripted(codes: Sequence[int], calls: list[tuple[str, ...]]):  # type: ignore[no-untyped-def]
    it = iter(codes)

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        calls.append(tuple(cmd))
        return next(it), "log"

    return run


def test_installer_smoke_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "dist" / "windows").mkdir(parents=True)
    (tmp_path / "dist" / "windows" / "n1mm-scope-bridge-setup-0.1.0.exe").write_bytes(b"MZ")
    monkeypatch.setattr(inst_step, "ROOT", tmp_path)
    calls: list[tuple[str, ...]] = []
    (step,) = inst_step.steps(StepContext(runner=scripted([0, 0], calls)))
    assert step.action is not None
    step.action()
    assert calls[0][-1] == "scripts/build_installer.py"
    assert calls[1][0] == "pwsh"
    assert calls[1][-3].endswith("n1mm-scope-bridge-setup-0.1.0.exe")
    assert calls[1][-2:] == ("-Payload", inst_step.local_payload())


@pytest.mark.parametrize(
    ("platform", "payload"),
    [("win-amd64", "x64"), ("win-arm64", "arm64"), ("win32", "x86"), ("linux-x86_64", "x64")],
)
def test_installer_smoke_forces_the_local_payload(platform: str, payload: str) -> None:
    assert inst_step.local_payload(platform) == payload


@pytest.mark.parametrize(
    ("codes", "installers", "message"),
    [([1], 1, "installer build failed"), ([0], 0, "found 0"), ([0, 3], 1, "smoke test failed")],
)
def test_installer_smoke_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, codes: list[int], installers: int, message: str
) -> None:
    out = tmp_path / "dist" / "windows"
    out.mkdir(parents=True)
    for i in range(installers):
        (out / f"n1mm-scope-bridge-setup-0.1.{i}.exe").write_bytes(b"MZ")
    monkeypatch.setattr(inst_step, "ROOT", tmp_path)
    with pytest.raises(CheckFailed, match=message):
        inst_step.installer_smoke(scripted(codes, []))
