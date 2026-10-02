# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="GUI needs PySide6 (not available on free-threaded Python)")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from n1mm_scope_bridge.gui import app as gui_app
from n1mm_scope_bridge.gui import screenshot as ss

pytestmark = pytest.mark.gui


def test_capture_writes_every_scene_with_manifest(qtbot: QtBot, tmp_path: Path) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    paths = ss.capture(tmp_path, app, dark=lambda _a: False)
    expected = {f"{s.name}{suffix}.png" for s in ss.SCENES for suffix in ("", "-dark")}
    assert {p.name for p in paths} == expected
    manifest = json.loads((tmp_path / ss.MANIFEST).read_text(encoding="utf-8"))
    assert list(manifest) == [s.name for s in ss.SCENES]
    main = manifest["main-window"]
    image = QImage(str(tmp_path / "main-window.png"))
    assert (image.width(), image.height()) == (main["width"], main["height"])
    assert (main["width"], main["height"]) == ss.WINDOW_SIZE
    assert all(entry["alt"] and entry["caption"] for entry in manifest.values())
    assert all(entry["dark"] == f"{name}-dark.png" for name, entry in manifest.items())
    light = QImage(str(tmp_path / "main-window.png")).pixelColor(4, 4).lightness()
    dark = QImage(str(tmp_path / "main-window-dark.png")).pixelColor(4, 4).lightness()
    assert dark < light  # the dark variant really is dark
    assert not (tmp_path / "screenshot-settings.json").exists()


def test_capture_is_deterministic(qtbot: QtBot, tmp_path: Path) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    ss.capture(tmp_path / "a", app, dark=lambda _a: False)
    ss.capture(tmp_path / "b", app, dark=lambda _a: False)
    for scene in ss.SCENES:
        a = QImage(str(tmp_path / "a" / f"{scene.name}.png"))
        b = QImage(str(tmp_path / "b" / f"{scene.name}.png"))
        assert a == b, scene.name


def test_demo_window_shows_streaming_state(qtbot: QtBot, tmp_path: Path) -> None:
    window = ss.demo_window(tmp_path / "s.json")
    qtbot.addWidget(window)
    assert window.chip.text() == "Streaming"
    assert window.status.text().startswith("Streaming to N1MM+")
    assert window.cards["frequency"].value.text() == "14.074 000 MHz"
    assert window.spectrum.rows_added == ss.WATERFALL_FRAMES
    assert "Started streaming" in window.log_view.toPlainText()
    assert window.tray is None
    window.quit_app()


def test_dark_supported_reports_platform_capability(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    assert isinstance(ss.dark_supported(app), bool)


def test_gui_main_screenshot_mode(
    qtbot: QtBot, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gui_app.main(["--screenshot", str(tmp_path)]) == 0
    assert f"Saved {2 * len(ss.SCENES)} screenshots" in capsys.readouterr().out
    assert (tmp_path / ss.MANIFEST).exists()
