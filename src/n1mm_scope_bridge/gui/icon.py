# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Application and tray icon, drawn at run time from the current palette.

A small waterfall (spectrum bars) on a rounded tile in the palette's
highlight colour, so it matches the user's light or dark theme and needs no
binary asset in the repository.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap

SIZES = (16, 24, 32, 48, 64, 128, 256)
BARS = (0.35, 0.55, 0.9, 0.6, 0.4, 0.75, 0.5)


def render(size: int, palette: QPalette) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    tile = QRectF(0, 0, size, size).adjusted(0.5, 0.5, -0.5, -0.5)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(palette.color(QPalette.ColorRole.Highlight))
    painter.drawRoundedRect(tile, size * 0.22, size * 0.22)
    bar_colour = QColor(palette.color(QPalette.ColorRole.HighlightedText))
    painter.setBrush(bar_colour)
    margin = size * 0.18
    width = (size - 2 * margin) / len(BARS)
    floor = size - margin
    for i, height in enumerate(BARS):
        top = floor - height * (size - 2 * margin)
        painter.drawRect(QRectF(margin + i * width + width * 0.15, top, width * 0.7, floor - top))
    painter.end()
    return pixmap


def app_icon(palette: QPalette) -> QIcon:
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(render(size, palette))
    return icon
