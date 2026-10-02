# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Center-mode prompt with copy-ready N1MM+ function-key macros (#92, #62).

Shown when the radio's scope is not in Center mode, because N1MM+ frequencies
are exact only in Center. The bridge never changes the radio itself and never
opens a COM port: it offers N1MM+ macros ("Scope Center", "Scope restore")
that N1MM+ sends over its own CAT port when the operator presses them. When
the scope reaches Center, the panel confirms it briefly and hides.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from n1mm_scope_bridge.center import CenterModeMonitor
from n1mm_scope_bridge.gui.widgets import Badge
from n1mm_scope_bridge.radios.base import ScopeStatus

CONFIRM_MS = 8000
PROMPT = (
    "The {model}'s scope is in {mode} mode, so N1MM+ frequencies are approximate. "
    "Set the scope to Center on the radio, or add these N1MM+ function-key macros "
    "(N1MM+ sends them on its own CAT port; the bridge never does):"
)
CONFIRMED = "✓ The {model}'s scope is in Center mode. N1MM+ frequencies are exact."
MACRO_NOTE = "Format UNVERIFIED on the radio (#62). Paste each line into the N1MM+ F-key editor."


class CenterModePanel(QFrame):
    """Prompt card: hidden in Center mode, shown with macros otherwise."""

    def __init__(
        self,
        model: str,
        *,
        log: Callable[[str], object] = lambda _m: None,
        confirm_ms: int = CONFIRM_MS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setAccessibleName("Center mode prompt")
        self._model = model
        self._log = log
        self.monitor = CenterModeMonitor(model, log)
        self._mode: str | None = None
        self._dismissed_mode: str | None = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(confirm_ms)
        self._hide_timer.timeout.connect(self.hide)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        top = QHBoxLayout()
        self.badge = Badge("Scope not in Center", role="chip")
        self.badge.set_kind("warning")
        top.addWidget(self.badge)
        top.addStretch(1)
        self.dismiss = QPushButton("Dismiss")
        self.dismiss.setAccessibleName("Dismiss the Center mode prompt")
        self.dismiss.clicked.connect(self._dismiss)
        top.addWidget(self.dismiss)
        layout.addLayout(top)
        self.message = QLabel("")
        self.message.setObjectName("message")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.macro_box = QWidget()
        self.macro_grid = QGridLayout(self.macro_box)
        self.macro_grid.setContentsMargins(0, 0, 0, 0)
        self.macro_grid.setHorizontalSpacing(8)
        layout.addWidget(self.macro_box)
        self.note = QLabel(MACRO_NOTE)
        self.note.setObjectName("cardDetail")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.copy_buttons: dict[str, QPushButton] = {}
        self.macro_fields: dict[str, QLineEdit] = {}
        self.hide()

    def reset(self, model: str | None = None) -> None:
        """Start of a new stream: forget the previous mode and restore code."""
        if model is not None:
            self._model = model
        self.monitor = CenterModeMonitor(self._model, self._log)
        self._mode = None
        self._dismissed_mode = None
        self._hide_timer.stop()
        self.hide()

    def observe(self, status: ScopeStatus) -> None:
        """Called on the GUI thread for every scope status update."""
        was_prompted = self.monitor.prompted
        self.monitor.observe(status)
        if status.mode_family == "center":
            if was_prompted and self.isVisible() and not self._hide_timer.isActive():
                self._show_confirmed()
            return
        if self._dismissed_mode == status.mode_name:
            return
        self._dismissed_mode = None
        self._show_prompt(status.mode_name)

    def _show_prompt(self, mode: str) -> None:
        self._mode = mode
        self._hide_timer.stop()
        self.badge.setText("Scope not in Center")
        self.badge.set_kind("warning")
        self.message.setText(PROMPT.format(model=self._model, mode=mode))
        self._fill_macros(self.monitor.macros())
        self.macro_box.show()
        self.note.show()
        self.dismiss.show()
        self.show()

    def _show_confirmed(self) -> None:
        self.badge.setText("Center mode")
        self.badge.set_kind("success")
        self.message.setText(CONFIRMED.format(model=self._model))
        self.macro_box.hide()
        self.note.hide()
        self.dismiss.hide()
        self._hide_timer.start()

    def _dismiss(self) -> None:
        """Hide until the scope changes to a different mode."""
        self._dismissed_mode = self._mode
        self.hide()

    def _fill_macros(self, macros: list[tuple[str, str]]) -> None:
        while self.macro_grid.count():
            item = self.macro_grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.copy_buttons.clear()
        self.macro_fields.clear()
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for row, (label, text) in enumerate(macros):
            name = QLabel(label)
            field = QLineEdit(f"{label},{text}")
            field.setReadOnly(True)
            field.setFont(mono)
            field.setAccessibleName(f"{label} macro")
            copy = QPushButton("Copy")
            copy.setAccessibleName(f"Copy the {label} macro")
            copy.clicked.connect(lambda _c=False, f=field, b=copy: self._copy(f, b))
            self.macro_grid.addWidget(name, row, 0)
            self.macro_grid.addWidget(field, row, 1)
            self.macro_grid.addWidget(copy, row, 2, Qt.AlignmentFlag.AlignRight)
            self.copy_buttons[label] = copy
            self.macro_fields[label] = field

    @staticmethod
    def _copy(field: QLineEdit, button: QPushButton) -> None:
        QApplication.clipboard().setText(field.text())
        button.setText("Copied")
        QTimer.singleShot(1500, lambda: button.setText("Copy"))
