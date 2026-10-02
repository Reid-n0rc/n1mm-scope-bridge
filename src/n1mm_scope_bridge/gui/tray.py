# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""System tray icon, the Close-button decision, and the close prompt (#19)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
    QWidget,
)

TRAY_HINT = "N1MM Scope Bridge is still running in the system tray. Right-click its icon to exit."


@dataclass(frozen=True)
class CloseDecision:
    action: str  # "tray", "exit", or "cancel"
    remember: str | None = None  # new on_close value to save, if the user ticked the box


Asker = Callable[[], tuple[str, bool]]


def decide_close(on_close: str, tray_available: bool, ask: Asker) -> CloseDecision:
    """What the window's Close button does, given the ``on_close`` setting."""
    if not tray_available:
        return CloseDecision("exit")
    if on_close in ("tray", "exit"):
        return CloseDecision(on_close)
    choice, remember = ask()
    if choice == "cancel":
        return CloseDecision("cancel")
    return CloseDecision(choice, choice if remember else None)


def build_close_box(
    parent: QWidget | None,
) -> tuple[QMessageBox, QAbstractButton, QAbstractButton, QCheckBox]:
    """The close prompt, not yet shown (also used for website screenshots)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Close N1MM Scope Bridge")
    box.setText("Keep streaming in the system tray, or exit N1MM Scope Bridge?")
    box.setInformativeText("Exiting stops the spectrum display in N1MM+.")
    tray = box.addButton("Keep running in tray", QMessageBox.ButtonRole.AcceptRole)
    exit_button = box.addButton("Exit", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(tray)
    remember = QCheckBox("Remember my choice")
    box.setCheckBox(remember)
    return box, tray, exit_button, remember


def ask_close(parent: QWidget | None) -> tuple[str, bool]:
    """Ask: keep streaming in the tray, exit, or cancel. Returns (choice, remember)."""
    box, tray, exit_button, remember = build_close_box(parent)
    box.exec()
    clicked = box.clickedButton()
    choice = "tray" if clicked is tray else "exit" if clicked is exit_button else "cancel"
    return choice, remember.isChecked()


class TrayController(QObject):
    """Tray icon with Show window / Start-Stop streaming / Exit."""

    show_requested = Signal()
    toggle_requested = Signal()
    exit_requested = Signal()

    def __init__(self, icon: QIcon, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.icon = QSystemTrayIcon(icon, self)
        self.menu = QMenu()
        self.show_action = QAction("Show window", self.menu)
        self.toggle_action = QAction("Start streaming", self.menu)
        self.exit_action = QAction("Exit", self.menu)
        self.menu.addAction(self.show_action)
        self.menu.addAction(self.toggle_action)
        self.menu.addSeparator()
        self.menu.addAction(self.exit_action)
        self.show_action.triggered.connect(self.show_requested)
        self.toggle_action.triggered.connect(self.toggle_requested)
        self.exit_action.triggered.connect(self.exit_requested)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        self.hint_shown = False
        self.set_status("Stopped", streaming=False)

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    def set_status(self, text: str, *, streaming: bool) -> None:
        self.icon.setToolTip(f"N1MM Scope Bridge: {text}")
        self.toggle_action.setText("Stop streaming" if streaming else "Start streaming")

    def show(self) -> None:
        self.icon.show()

    def hint_once(self) -> None:
        """Tell the user, once per session, that the program keeps running in the tray."""
        if not self.hint_shown:
            self.hint_shown = True
            self.icon.showMessage("N1MM Scope Bridge", TRAY_HINT)
