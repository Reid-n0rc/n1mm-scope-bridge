# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6", reason="GUI needs PySide6 (not available on free-threaded Python)")

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QFileDialog, QGroupBox, QMessageBox, QPushButton
from pytestqt.qtbot import QtBot

from n1mm_scope_bridge.gui import app as gui_app
from n1mm_scope_bridge.gui import main_window as mw
from n1mm_scope_bridge.gui.controller import StreamController
from n1mm_scope_bridge.gui.main_window import MainWindow
from n1mm_scope_bridge.gui.style import STYLESHEET, apply_style, choose_style
from n1mm_scope_bridge.pipeline import PipelineStats
from n1mm_scope_bridge.radios.base import ScopeStatus
from n1mm_scope_bridge.settings import Settings
from n1mm_scope_bridge.transport.ft4222 import FTDI_DOWNLOAD_URL, Ft4222Reader, LibraryNotFound

pytestmark = pytest.mark.gui


@pytest.fixture
def listener() -> Iterator[socket.socket]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(5)
        yield rx


class Recorder:
    def __init__(self) -> None:
        self.saved: list[Settings] = []
        self.urls: list[str] = []

    def save(self, settings: Settings, path: Path | None) -> None:
        self.saved.append(settings)

    def open_url(self, url: QUrl) -> None:
        self.urls.append(url.toString())


def make_window(
    qtbot: QtBot, settings: Settings | None = None, **kw: Any
) -> tuple[MainWindow, Recorder]:
    rec = Recorder()
    window = MainWindow(settings or Settings(), save=rec.save, open_url=rec.open_url, **kw)
    qtbot.addWidget(window)
    return window, rec


# --- style -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (["Windows", "windows11", "Fusion"], "windows11"),
        (["windowsvista", "Fusion"], "Fusion"),
        (["macOS", "fusion"], "fusion"),
        ([], "Fusion"),
    ],
)
def test_choose_style(available: list[str], expected: str) -> None:
    assert choose_style(available) == expected


def test_apply_style_uses_palette_only(qapp: QApplication) -> None:
    assert apply_style(qapp) in ("windows11", "Fusion", "fusion")
    assert qapp.styleSheet() == STYLESHEET
    assert "#" not in STYLESHEET.replace("QLabel#", "").replace(
        "QPushButton#", ""
    )  # no hex colours


# --- form ----------------------------------------------------------------------------


def test_form_round_trips_settings(qtbot: QtBot) -> None:
    original = Settings(
        source_name="Shack", n1mm_host="10.0.0.5", n1mm_port=12345, rate_hz=5.0,
        combine="peak", scaling=0.25, emulator=True,
    )  # fmt: skip
    window, _ = make_window(qtbot, original)
    assert window.form_settings() == original
    assert window.chip.text() == "Stopped"
    assert window.source_name.placeholderText() == "Shack"


def test_edits_validate_inline_and_autosave(qtbot: QtBot) -> None:
    window, rec = make_window(qtbot)
    window.host.setText(" ")
    assert window._errors["n1mm_host"].isVisible() or window._errors["n1mm_host"].text()
    assert "N1MM+ PC" in window._errors["n1mm_host"].text()
    qtbot.waitUntil(lambda: bool(rec.saved), timeout=3000)
    assert rec.saved[-1].n1mm_host == ""
    window.host.setText("127.0.0.1")
    assert window._errors["n1mm_host"].text() == ""


def test_start_with_invalid_settings_shows_error(qtbot: QtBot) -> None:
    window, _ = make_window(qtbot)
    window.host.setText("")
    window.toggle_streaming()
    assert window.chip.text() == "Error"
    assert "Fix the highlighted settings" in window.status.text()
    assert not window.controller.running


def test_browse_sets_folder(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    window, _ = make_window(qtbot)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(tmp_path))
    window._browse_ftdi()
    assert window.ftdi_dir.text() == str(tmp_path)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: "")
    window._browse_ftdi()
    assert window.ftdi_dir.text() == str(tmp_path)


def test_setup_guide_button_opens_docs(qtbot: QtBot) -> None:
    window, rec = make_window(qtbot)
    guide = next(b for b in window.findChildren(QPushButton) if b.text() == "N1MM+ setup guide")
    guide.click()
    assert rec.urls == [mw.SETUP_GUIDE_URL]


def test_save_failure_is_reported(qtbot: QtBot) -> None:
    def broken(settings: Settings, path: Path | None) -> None:
        raise OSError("read-only folder")

    window = MainWindow(Settings(), save=broken)
    qtbot.addWidget(window)
    window.save_settings()
    assert "Could not save settings: read-only folder" in window.status.text()


# --- streaming ------------------------------------------------------------------------


def test_start_stop_with_emulator(qtbot: QtBot, listener: socket.socket) -> None:
    settings = Settings(emulator=True, n1mm_port=listener.getsockname()[1], rate_hz=10.0)
    window, rec = make_window(qtbot, settings)
    with qtbot.waitSignal(window.controller.started, timeout=3000):
        window.start_stop.click()
    assert window.chip.text() == "Streaming"
    assert window.start_stop.text() == "Stop"
    boxes = {box.objectName(): box.isEnabled() for box in window.findChildren(QGroupBox)}
    assert boxes["behaviourBox"] is True  # closing/startup choices stay editable
    assert not any(enabled for name, enabled in boxes.items() if name != "behaviourBox")
    assert b"<Spectrum>" in listener.recvfrom(65535)[0]
    qtbot.waitUntil(lambda: window.status.text().startswith("VFO 14.074000 MHz"), timeout=3000)
    qtbot.waitUntil(lambda: window.counters.text().startswith("Sent"), timeout=3000)
    assert rec.saved  # settings saved on Start
    with qtbot.waitSignal(window.controller.stopped, timeout=6000):
        window.start_stop.click()
    assert window.chip.text() == "Stopped"
    assert window.start_stop.text() == "Start"


def test_missing_ftdi_library_offers_download(qtbot: QtBot) -> None:
    def missing(_: Settings) -> Any:
        raise LibraryNotFound("Could not load FTDI's LibFT4222/D2XX libraries")

    rec = Recorder()
    controller = StreamController(source_factory=missing)
    window = MainWindow(Settings(), save=rec.save, open_url=rec.open_url, controller=controller)
    qtbot.addWidget(window)
    window.toggle_streaming()
    assert window.chip.text() == "Error"
    box = window.findChild(QMessageBox)
    assert box is not None
    assert "Could not load FTDI" in box.text()
    download = next(b for b in box.buttons() if b.text() == "Open FTDI download page")
    download.click()
    assert rec.urls == [FTDI_DOWNLOAD_URL]


def test_status_and_stats_text() -> None:
    status = ScopeStatus(14_074_000, 20_000, "center", "Center (Normal)")
    assert mw.status_text(status) == "VFO 14.074000 MHz · span 20 kHz · Center (Normal)"
    assert mw.stats_text(PipelineStats(10, 1, 2, 4)) == "Sent 4 · dropped 1 · bad 2"


def test_non_center_mode_hint(qtbot: QtBot) -> None:
    window, _ = make_window(qtbot)
    window._on_status(ScopeStatus(1_000_000, 1_000, "cursor", "Cursor (Normal)"))
    assert "Center mode" in window.status.text()


def test_close_stops_and_saves(qtbot: QtBot) -> None:
    window, rec = make_window(qtbot)
    window.show()
    window.close()
    assert rec.saved


def test_gui_source(monkeypatch: pytest.MonkeyPatch) -> None:
    reader, close = mw.gui_source(Settings(emulator=True))
    assert isinstance(reader, Ft4222Reader)
    close()
    sentinel: Any = ("radio", None)
    monkeypatch.setattr(mw, "radio_source", lambda s: sentinel)
    assert mw.gui_source(Settings()) is sentinel


# --- app entry point ---------------------------------------------------------------------


def test_self_test_passes(qapp: QApplication, tmp_path: Path) -> None:
    ok, message = gui_app.self_test(qapp, tmp_path / "st.json")
    assert ok, message
    assert "self-test: OK" in message


def test_main_self_test(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert gui_app.main(["--self-test", "--settings", str(tmp_path / "s.json")]) == 0
    assert "self-test: OK" in capsys.readouterr().out


def test_self_test_failure_reported(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(gui_app, "self_test", lambda app, path: (False, "self-test: received 0"))
    assert gui_app.main(["--self-test", "--settings", str(tmp_path / "s.json")]) == 1
    assert "received 0" in capsys.readouterr().err


def test_main_opens_window_and_autostarts(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"start_streaming_on_launch": true, "emulator": true, "rate_hz": "x"}')
    started: list[MainWindow] = []

    def fake_toggle(self: MainWindow) -> None:
        started.append(self)

    monkeypatch.setattr(MainWindow, "toggle_streaming", fake_toggle)
    errors: list[str] = []
    monkeypatch.setattr(MainWindow, "show_error", lambda self, m: errors.append(m))
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    assert gui_app.main(["--settings", str(path)]) == 0
    assert len(started) == 1
    assert "rate_hz" in errors[0]
    started[0].close()


def test_parser_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        gui_app.build_parser().parse_args(["--version"])
    assert "n1mm-scope-bridge-gui" in capsys.readouterr().out


def test_self_test_reports_missing_packets(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gui_app, "SELF_TEST_TIMEOUT_S", 0.0)
    ok, message = gui_app.self_test(qapp, tmp_path / "st.json")
    assert not ok
    assert "received 0 N1MM packets" in message
