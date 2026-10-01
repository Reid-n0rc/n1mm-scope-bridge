# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""System tray, the close prompt, and minimize-to-tray (#19)."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6", reason="GUI needs PySide6 (not available on free-threaded Python)")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
from pytestqt.qtbot import QtBot

from n1mm_scope_bridge.gui import app as gui_app
from n1mm_scope_bridge.gui import main_window as mw
from n1mm_scope_bridge.gui import tray as tray_mod
from n1mm_scope_bridge.gui.icon import SIZES, app_icon, render
from n1mm_scope_bridge.gui.main_window import MainWindow
from n1mm_scope_bridge.gui.tray import CloseDecision, TrayController, decide_close
from n1mm_scope_bridge.settings import Settings

pytestmark = pytest.mark.gui


@pytest.fixture
def listener() -> Iterator[socket.socket]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(5)
        yield rx


def window_with_tray(
    qtbot: QtBot, settings: Settings | None = None, answer: tuple[str, bool] = ("tray", False)
) -> tuple[MainWindow, list[Settings], list[int]]:
    saved: list[Settings] = []
    asked: list[int] = []

    def ask() -> tuple[str, bool]:
        asked.append(1)
        return answer

    window = MainWindow(
        settings or Settings(),
        save=lambda s, p: saved.append(s),
        tray_available=lambda: True,
        ask=ask,
    )
    qtbot.addWidget(window)
    return window, saved, asked


# --- pure close decision ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("on_close", "answer", "expected"),
    [
        ("tray", None, CloseDecision("tray")),
        ("exit", None, CloseDecision("exit")),
        ("ask", ("tray", False), CloseDecision("tray")),
        ("ask", ("tray", True), CloseDecision("tray", "tray")),
        ("ask", ("exit", True), CloseDecision("exit", "exit")),
        ("ask", ("cancel", True), CloseDecision("cancel")),
    ],
)
def test_decide_close(
    on_close: str, answer: tuple[str, bool] | None, expected: CloseDecision
) -> None:
    def ask() -> tuple[str, bool]:
        assert answer is not None, "should not ask"
        return answer

    assert decide_close(on_close, True, ask) == expected


def test_no_tray_means_close_exits() -> None:
    assert decide_close("tray", False, lambda: ("cancel", False)) == CloseDecision("exit")


# --- icon -----------------------------------------------------------------------------------


def test_icon_has_all_sizes(qapp: QApplication) -> None:
    icon = app_icon(qapp.palette())
    assert sorted(s.width() for s in icon.availableSizes()) == sorted(SIZES)
    assert not render(32, qapp.palette()).isNull()


# --- close prompt dialog ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("button", "expected"), [("Keep running in tray", "tray"), ("Exit", "exit")]
)
def test_ask_close_dialog(qtbot: QtBot, button: str, expected: str) -> None:
    def click() -> None:
        box = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox))
        box.checkBox().setChecked(True)
        next(b for b in box.buttons() if b.text() == button).click()

    QTimer.singleShot(50, click)
    assert tray_mod.ask_close(None) == (expected, True)


def test_ask_close_cancel(qtbot: QtBot) -> None:
    def cancel() -> None:
        box = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox))
        box.button(QMessageBox.StandardButton.Cancel).click()

    QTimer.singleShot(50, cancel)
    assert tray_mod.ask_close(None) == ("cancel", False)


# --- tray controller ----------------------------------------------------------------------


def test_tray_menu_and_tooltip(qtbot: QtBot, qapp: QApplication) -> None:
    tray = TrayController(app_icon(qapp.palette()))
    assert [a.text() for a in tray.menu.actions() if a.text()] == [
        "Show window", "Start streaming", "Exit",
    ]  # fmt: skip
    tray.set_status("Streaming", streaming=True)
    assert tray.icon.toolTip() == "N1MM Scope Bridge: Streaming"
    assert tray.toggle_action.text() == "Stop streaming"
    with qtbot.waitSignal(tray.show_requested):
        tray._activated(QSystemTrayIcon.ActivationReason.DoubleClick)
    with qtbot.assertNotEmitted(tray.show_requested):
        tray._activated(QSystemTrayIcon.ActivationReason.Context)
    for action, signal in (
        (tray.show_action, tray.show_requested),
        (tray.toggle_action, tray.toggle_requested),
        (tray.exit_action, tray.exit_requested),
    ):
        with qtbot.waitSignal(signal):
            action.trigger()


def test_hint_shown_once(qtbot: QtBot, qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    tray = TrayController(app_icon(qapp.palette()))
    shown: list[str] = []
    monkeypatch.setattr(tray.icon, "showMessage", lambda title, text: shown.append(text))
    tray.hint_once()
    tray.hint_once()
    assert shown == [tray_mod.TRAY_HINT]


# --- window behaviour ------------------------------------------------------------------------


def test_close_to_tray_keeps_streaming(qtbot: QtBot, listener: socket.socket) -> None:
    settings = Settings(emulator=True, n1mm_port=listener.getsockname()[1], rate_hz=10.0)
    window, _, asked = window_with_tray(qtbot, settings, ("tray", False))
    window.show()
    with qtbot.waitSignal(window.controller.started, timeout=3000):
        window.toggle_streaming()
    window.close()
    assert asked == [1]
    assert not window.isVisible()
    assert window.controller.running
    listener.recvfrom(65535)
    listener.recvfrom(65535)  # still streaming while hidden
    window.show_window()
    assert window.isVisible()
    window.quit_app()
    assert not window.controller.running


def test_remembered_choice_is_saved_and_not_asked_again(qtbot: QtBot) -> None:
    window, saved, asked = window_with_tray(qtbot, answer=("tray", True))
    window.show()
    window.close()
    assert saved[-1].on_close == "tray"
    assert window.on_close.currentData() == "tray"
    window.show()
    window.close()
    assert asked == [1]


def test_cancel_keeps_window_open(qtbot: QtBot) -> None:
    window, _, _ = window_with_tray(qtbot, answer=("cancel", False))
    window.show()
    window.close()
    assert window.isVisible()


def test_exit_choice_quits(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    quits: list[int] = []
    monkeypatch.setattr(mw, "quit_application", lambda: quits.append(1))
    window, _, _ = window_with_tray(qtbot, answer=("exit", False))
    window.show()
    window.close()
    assert not window.isVisible()
    assert quits == [1]
    assert window.tray is not None
    assert not window.tray.icon.isVisible()


def test_minimize_hides_to_tray(qtbot: QtBot) -> None:
    window, _, _ = window_with_tray(qtbot)
    window.show()
    window.showMinimized()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=2000)
    assert window.tray is not None
    assert window.tray.hint_shown


def test_no_tray_minimizes_normally(qtbot: QtBot) -> None:
    window = MainWindow(Settings(), save=lambda s, p: None, tray_available=lambda: False)
    qtbot.addWidget(window)
    assert window.tray is None
    window.hide_to_tray()  # falls back to a normal minimize
    window.show()
    window.close()
    assert not window.isVisible()


def test_tray_toggle_shows_window_on_error(qtbot: QtBot) -> None:
    window, _, _ = window_with_tray(qtbot, Settings(n1mm_host=""))
    window.hide()
    assert window.tray is not None
    window.tray.toggle_requested.emit()
    assert window.chip.text() == "Error"
    assert window.isVisible()


def test_behaviour_settings_round_trip(qtbot: QtBot) -> None:
    s = Settings(start_streaming_on_launch=True, start_minimized=True, on_close="exit")
    window, _, _ = window_with_tray(qtbot, s)
    assert window.form_settings() == s


def test_app_starts_hidden_in_tray(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"start_minimized": true}')
    windows: list[MainWindow] = []
    real_init: Any = MainWindow.__init__

    def init(self: MainWindow, *a: Any, **kw: Any) -> None:
        kw["tray_available"] = lambda: True
        real_init(self, *a, **kw)
        windows.append(self)

    monkeypatch.setattr(MainWindow, "__init__", init)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    assert gui_app.main(["--settings", str(path)]) == 0
    assert not windows[0].isVisible()
    assert not qapp.quitOnLastWindowClosed()
    qapp.setQuitOnLastWindowClosed(True)
    windows[0].quit_app()
