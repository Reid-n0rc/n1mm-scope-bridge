# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Small building blocks for the dashboard: cards, status pills, and chips.

Appearance comes from object names and properties styled in ``style.py``;
nothing here hard-codes a colour.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

KINDS = ("neutral", "success", "warning", "danger")


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class Badge(QLabel):
    """A rounded label (``pill`` in the header, ``chip`` inside cards)."""

    def __init__(self, text: str = "", *, role: str = "chip", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName(role)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_kind("neutral")

    @property
    def kind(self) -> str:
        return str(self.property("kind"))

    def set_kind(self, kind: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown badge kind {kind!r}")
        self.setProperty("kind", kind)
        repolish(self)


class Card(QFrame):
    """Title, a large value, an optional detail line, and an optional chip."""

    def __init__(self, title: str, *, monospace: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.value = QLabel("—")
        self.value.setObjectName("cardValue")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.value.setAccessibleName(title)
        if monospace:
            font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
            self.value.setFont(font)
        self.detail = QLabel("")
        self.detail.setObjectName("cardDetail")
        self.detail.setWordWrap(True)
        self.chip = Badge()
        self.chip.hide()
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)
        layout.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def show_chip(self, text: str, kind: str) -> None:
        self.chip.setText(text)
        self.chip.set_kind(kind)
        self.chip.setVisible(bool(text))
