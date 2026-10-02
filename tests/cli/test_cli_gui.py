# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from cliutil import cli


def test_gui_without_pyside6_explains_how_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "n1mm_scope_bridge.gui.app", None)  # import fails
    code, _, err = cli("gui")
    assert code == 1
    assert "The window needs PySide6" in err
    assert 'pip install "n1mm-scope-bridge[gui]"' in err


def test_gui_passes_options_to_the_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("PySide6", reason="GUI needs PySide6")
    from n1mm_scope_bridge.gui import app  # noqa: PLC0415 - optional dependency

    seen: list[list[str]] = []

    def fake_main(argv: list[str]) -> int:
        seen.append(list(argv))
        return 0

    monkeypatch.setattr(app, "main", fake_main)
    code, _, _ = cli("gui", "--settings", str(tmp_path / "s.json"), "--self-test")
    assert code == 0
    assert seen == [["--settings", str(tmp_path / "s.json"), "--self-test"]]
    cli("gui")
    assert seen[-1] == []
    cli("gui", "--screenshot", str(tmp_path / "shots"), "--source", "radio",
        "--ftdi-lib-dir", str(tmp_path), "--settle", "5")  # fmt: skip
    assert seen[-1] == [
        "--screenshot", str(tmp_path / "shots"), "--source", "radio",
        "--ftdi-lib-dir", str(tmp_path), "--settle", "5.0",
    ]  # fmt: skip


@pytest.mark.gui
def test_gui_self_test_end_to_end(tmp_path: Path) -> None:
    pytest.importorskip("PySide6", reason="GUI needs PySide6")
    code, _, err = cli("gui", "--self-test", "--settings", str(tmp_path / "s.json"))
    assert code == 0, err
