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
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from n1mm_scope_bridge.gui import app as gui_app
from n1mm_scope_bridge.gui import main_window as mw
from n1mm_scope_bridge.gui.controller import StreamController
from n1mm_scope_bridge.gui.main_window import MainWindow
from n1mm_scope_bridge.gui.style import (
    Theme,
    apply_style,
    build_stylesheet,
    choose_style,
    dark_palette,
)
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


def test_apply_style_builds_stylesheet_from_palette(qapp: QApplication) -> None:
    assert apply_style(qapp) in ("windows11", "Fusion", "fusion")
    theme = Theme.from_palette(qapp.palette())
    assert qapp.styleSheet() == build_stylesheet(theme)
    assert theme.accent.name() in qapp.styleSheet()


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
    assert window.chip.kind == "danger"
    assert "Fix the highlighted settings" in window.status.text()
    assert not window.controller.running
    dialog = window.settings_dialog
    assert dialog.isVisible()  # opened on the page with the problem
    assert dialog.stack.currentWidget() is dialog.pages["N1MM+"]


def test_browse_sets_folder(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    window, _ = make_window(qtbot)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(tmp_path))
    window._browse_ftdi()
    assert window.ftdi_dir.text() == str(tmp_path)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: "")
    window._browse_ftdi()
    assert window.ftdi_dir.text() == str(tmp_path)


def test_setup_guide_menu_opens_docs(qtbot: QtBot) -> None:
    window, rec = make_window(qtbot)
    assert window.action_guide in window.menu.actions()
    window.action_guide.trigger()
    assert rec.urls == [mw.SETUP_GUIDE_URL]


def test_menu_actions(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    window, _ = make_window(qtbot)
    texts = [a.text() for a in window.menu.actions()]
    assert texts == [
        "Settings…",
        "Copy diagnostics",
        "Copy diagnostics including source name",
        "N1MM+ setup guide",
        "About and license",
    ]
    window.action_settings.trigger()
    assert window.settings_dialog.isVisible()
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "about", lambda parent, title, text: shown.append(text))
    window.action_about.trigger()
    assert "GNU General Public License" in shown[0]
    window.action_diagnostics_named.trigger()
    assert "including source name" in window.log.lines()[-1]


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
    pages = window.settings_dialog.pages
    assert pages["Startup and closing"].fields.isEnabled()  # closing stays editable
    assert not pages["Radio"].fields.isEnabled()
    assert pages["Radio"].locked.isVisibleTo(pages["Radio"])
    assert b"<Spectrum>" in listener.recvfrom(65535)[0]
    qtbot.waitUntil(
        lambda: window.cards["frequency"].value.text() == "14.074 000 MHz", timeout=3000
    )
    qtbot.waitUntil(lambda: window.spectrum.frame is not None, timeout=3000)
    qtbot.waitUntil(lambda: "total" in window.status_rows["Sent to N1MM+"], timeout=3000)
    assert window.status.text().startswith("Streaming to N1MM+ at 127.0.0.1:")
    assert rec.saved  # settings saved on Start
    with qtbot.waitSignal(window.controller.stopped, timeout=6000):
        window.start_stop.click()
    assert window.chip.text() == "Stopped"
    assert window.start_stop.text() == "Start"
    assert pages["Radio"].fields.isEnabled()


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


def test_non_center_mode_hint(qtbot: QtBot) -> None:
    window, _ = make_window(qtbot)
    window._on_status(ScopeStatus(1_000_000, 1_000, "cursor", "Cursor (Normal)"))
    assert "Center mode" in window.status.text()
    mode = window.cards["mode"]
    assert mode.value.text() == "Cursor"
    assert mode.chip.kind == "warning"
    window._on_status(ScopeStatus(1_000_000, 1_000, "center", "Center (Normal)"))
    assert mode.chip.kind == "success"


def test_frequency_and_mode_text() -> None:
    assert mw.frequency_text(14_074_000) == "14.074 000 MHz"
    assert mw.frequency_text(7_000_001) == "7.000 001 MHz"
    assert mw.short_mode("Center (Normal)") == "Center"
    assert mw.short_mode("3DSS Center") == "3DSS Center"


def test_health_card_reports_problems(qtbot: QtBot) -> None:
    window, _ = make_window(qtbot)
    window.model.started()
    window.model.stats = PipelineStats(frames_read=10, frames_dropped=2, bad_frames=1, emitted=3)
    window._refresh_status()
    assert window.cards["health"].value.text() == "Degraded"
    assert window.cards["health"].detail.text() == "2 dropped · 1 bad"
    window.model.stopped("USB unplugged")
    window._refresh_status()
    assert window.cards["health"].value.text() == "Problem"
    assert window.cards["health"].chip.kind == "danger"


def test_activity_drawer_collapsed_by_default(qtbot: QtBot) -> None:
    window, _ = make_window(qtbot)
    window.show()
    assert not window.log_view.isVisible()
    window.activity_toggle.click()
    assert window.log_view.isVisible()
    window._log("info", "hello")
    assert window.activity_last.text().endswith("info: hello")
    window.set_activity_open(False)
    assert not window.log_view.isVisible()


def test_settings_dialog_round_trips_new_fields(qtbot: QtBot) -> None:
    original = Settings(device="FT4222 B", rate_hz=2.5, combine="average")
    window, _ = make_window(qtbot, original)
    assert window.form_settings() == original
    assert window.settings_dialog.rate_label.text() == "2.5 per second"
    window.rate.setValue(7)
    assert window.form_settings().rate_hz == 3.5
    assert window.settings_dialog.rate_label.text() == "3.5 per second"


def test_palette_change_reapplies_icons(qtbot: QtBot) -> None:
    window, _ = make_window(qtbot)
    before = window.start_stop.icon().cacheKey()
    window.setPalette(dark_palette())
    assert window.start_stop.icon().cacheKey() != before


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


def test_self_test_never_prompts_with_a_tray(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On a desktop with a system tray, closing normally asks the operator.
    def window_with_tray(*args: Any, **kwargs: Any) -> MainWindow:
        def ask() -> tuple[str, bool]:
            raise AssertionError("self-test prompted the operator")

        return MainWindow(*args, tray_available=lambda: True, ask=ask, **kwargs)

    monkeypatch.setattr(gui_app, "MainWindow", window_with_tray)
    ok, message = gui_app.self_test(qapp, tmp_path / "st.json")
    assert ok, message


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


def test_window_status_panel_log_and_diagnostics(qtbot: QtBot, listener: socket.socket) -> None:
    settings = Settings(emulator=True, n1mm_port=listener.getsockname()[1], rate_hz=10.0)
    window = MainWindow(settings, save=lambda s, p: None, tray_available=lambda: True)
    qtbot.addWidget(window)
    with qtbot.waitSignal(window.controller.started, timeout=3000):
        window.toggle_streaming()
    qtbot.waitUntil(lambda: window.status_rows["VFO"] == "14.074000 MHz", timeout=3000)
    qtbot.waitUntil(lambda: "per second" in window.status_rows["Sent to N1MM+"], timeout=3000)
    assert window.tray is not None
    assert window.tray.icon.toolTip().startswith("N1MM Scope Bridge: Streaming FT-710 to N1MM+")
    assert "Streaming to N1MM+" in window.log_view.toPlainText()
    window.controller.warning.emit("scope is in Cursor mode")
    qtbot.waitUntil(lambda: "warning: scope is in Cursor mode" in window.log_view.toPlainText())
    text = window.copy_diagnostics()
    assert QApplication.clipboard().text() == text
    assert "Diagnostics copied" in window.log_view.toPlainText()
    with qtbot.waitSignal(window.controller.stopped, timeout=6000):
        window.toggle_streaming()
    assert "Stopped streaming" in window.log_view.toPlainText()
    window.quit_app()


def test_window_shows_center_prompt_for_cursor_mode(qtbot: QtBot) -> None:
    window, _ = make_window(qtbot)
    window.show()
    window._on_status(ScopeStatus(7_074_000, 10_000, "cursor", "Cursor (Normal)"))
    assert window.center_panel.isVisible()
    assert "Scope Center" in window.center_panel.macro_fields
    window._on_started()
    assert not window.center_panel.isVisible()
