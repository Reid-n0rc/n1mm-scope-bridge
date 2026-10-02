# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Live preview of exactly what is sent to N1MM+: a spectrum line over a waterfall.

Drawn with ``QPainter`` once per N1MM update (a few times a second). The
waterfall is a ring buffer of rows in a ``QImage``, so adding a row is cheap.
Chrome colours come from the palette (``style.Theme``); the waterfall colour
map is data, not chrome, and is the one fixed palette here.
"""

from __future__ import annotations

import itertools
import math
from collections import deque

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from n1mm_scope_bridge.gui.style import Theme, mix
from n1mm_scope_bridge.spectrum import SpectrumFrame

HISTORY_ROWS = 160
PEAK_MEMORY = 60  # updates over which the level scale adapts
MIN_TOP_DB = 40.0
DB_GRID = 20.0
AXIS_HEIGHT = 22
SCALE_WIDTH = 44
SPECTRUM_SHARE = 0.42  # top part of the plot; the waterfall gets the rest
PLACEHOLDER = (
    "Press Start to stream your Yaesu scope to N1MM+",
    "No radio? Turn on Settings → Radio → Use the built-in emulator",
)

# Waterfall colour map stops (level 0..1): dark blue -> blue -> cyan -> yellow -> red.
COLOUR_STOPS = (
    (0.00, (8, 10, 40)),
    (0.30, (20, 60, 170)),
    (0.55, (20, 190, 210)),
    (0.78, (250, 220, 40)),
    (1.00, (230, 40, 30)),
)


def colour_map(steps: int = 256) -> list[int]:
    """ARGB values for levels 0..steps-1, interpolated between ``COLOUR_STOPS``."""
    table = []
    for i in range(steps):
        x = i / (steps - 1)
        for (x0, c0), (x1, c1) in itertools.pairwise(COLOUR_STOPS):
            if x <= x1:
                t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
                r, g, b = (round(a + (bb - a) * t) for a, bb in zip(c0, c1, strict=True))
                table.append(0xFF000000 | (r << 16) | (g << 8) | b)
                break
    return table


LUT = colour_map()


def format_khz(hz: int) -> str:
    return f"{hz / 1000:,.1f} kHz".replace(",", " ")


class SpectrumView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("spectrum")
        self.setAccessibleName("Spectrum and waterfall preview")
        self.setMinimumSize(QSize(320, 180))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.frame: SpectrumFrame | None = None
        self.scaling = 0.3125
        self.rows_added = 0
        self._image: QImage | None = None
        self._next_row = 0
        self._edges: tuple[int, int] | None = None
        self._peaks: deque[float] = deque(maxlen=PEAK_MEMORY)

    # -- data --------------------------------------------------------------------

    def clear(self) -> None:
        self.frame = None
        self._image = None
        self._edges = None
        self._next_row = 0
        self.rows_added = 0
        self._peaks.clear()
        self.update()

    def top_db(self) -> float:
        """Top of the level scale: recent peak plus headroom, in 20 dB steps."""
        if self.frame is None:
            return MIN_TOP_DB
        full = self.frame.max_level * self.scaling
        peak = max(self._peaks, default=0.0)
        top = math.ceil((peak + 6) / DB_GRID) * DB_GRID
        return max(MIN_TOP_DB, min(full, top))

    def set_frame(self, frame: SpectrumFrame, scaling: float) -> None:
        """Show ``frame`` and push it onto the waterfall."""
        bins = len(frame.levels)
        span = (frame.low_hz, frame.high_hz)
        if self._image is None or self._image.width() != bins or self._edges != span:
            self._image = QImage(bins, HISTORY_ROWS, QImage.Format.Format_RGB32)
            self._image.fill(QColor.fromRgb(LUT[0]))
            self._next_row = 0
        self._edges = span
        self.frame = frame
        self.scaling = scaling
        self._peaks.append(max(frame.levels) * scaling)
        top = max(1, frame.max_level)
        row = self._next_row
        for x, level in enumerate(frame.levels):
            self._image.setPixel(x, row, LUT[min(255, level * 255 // top)])
        # Rows are written bottom-up so that, read top-down from just after the
        # newest row, the image runs newest -> oldest without any flipping.
        self._next_row = (row - 1) % HISTORY_ROWS
        self.rows_added += 1
        self.update()

    def waterfall_row(self, age: int) -> list[int]:
        """Pixel values of the row ``age`` updates ago (0 = newest), for tests."""
        if self._image is None:
            return []
        row = (self._next_row + 1 + age) % HISTORY_ROWS
        return [self._image.pixel(x, row) for x in range(self._image.width())]

    # -- painting -------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        return QSize(880, 300)

    def plot_rect(self) -> QRect:
        return self.rect().adjusted(SCALE_WIDTH, 8, -12, -AXIS_HEIGHT)

    def paintEvent(self, event: QPaintEvent) -> None:
        theme = Theme.from_palette(self.palette())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = self.plot_rect()
        background = mix(theme.card, QColor("#000000"), 0.35 if theme.dark else 0.04)
        painter.fillRect(plot, background)
        if self.frame is None or self._image is None:
            self._paint_placeholder(painter, plot, theme)
        else:
            split = plot.top() + round(plot.height() * SPECTRUM_SHARE)
            spectrum = QRect(plot.left(), plot.top(), plot.width(), split - plot.top())
            waterfall = QRect(plot.left(), split, plot.width(), plot.bottom() - split + 1)
            self._paint_waterfall(painter, waterfall)
            self._paint_spectrum(painter, spectrum, theme)
            self._paint_axes(painter, plot, spectrum, theme)
        painter.end()

    def _paint_placeholder(self, painter: QPainter, plot: QRect, theme: Theme) -> None:
        painter.setPen(theme.text)
        font = painter.font()
        font.setPointSizeF(font.pointSizeF() * 1.25)
        font.setBold(True)
        painter.setFont(font)
        first = QRect(plot.left(), plot.center().y() - 26, plot.width(), 24)
        painter.drawText(first, Qt.AlignmentFlag.AlignCenter, PLACEHOLDER[0])
        font.setBold(False)
        font.setPointSizeF(font.pointSizeF() / 1.25)
        painter.setFont(font)
        painter.setPen(theme.secondary)
        second = QRect(plot.left(), plot.center().y() + 4, plot.width(), 22)
        painter.drawText(second, Qt.AlignmentFlag.AlignCenter, PLACEHOLDER[1])

    def _paint_waterfall(self, painter: QPainter, area: QRect) -> None:
        assert self._image is not None
        # Newest row at the top: rows [next+1 .. end] then [0 .. next].
        image, start = self._image, (self._next_row + 1) % HISTORY_ROWS
        row_h = area.height() / HISTORY_ROWS
        recent = image.copy(0, start, image.width(), HISTORY_ROWS - start)
        older = image.copy(0, 0, image.width(), start)
        painter.save()
        painter.setClipRect(area)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        top = float(area.top())
        for part in (recent, older):
            if part.height() == 0:
                continue
            height = part.height() * row_h
            painter.drawImage(QRectF(area.left(), top, area.width(), height), part)
            top += height
        painter.restore()

    def _paint_spectrum(self, painter: QPainter, area: QRect, theme: Theme) -> None:
        assert self.frame is not None
        levels = self.frame.levels
        top_db = self.top_db()
        grid = QPen(theme.border)
        grid.setWidth(1)
        painter.setPen(grid)
        db = DB_GRID
        while db < top_db:
            y = area.bottom() - db / top_db * area.height()
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            db += DB_GRID
        n = len(levels)
        path = QPainterPath()
        for i, level in enumerate(levels):
            x = area.left() + i * (area.width() - 1) / max(1, n - 1)
            y = area.bottom() - min(1.0, level * self.scaling / top_db) * area.height()
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        fill = QPainterPath(path)
        fill.lineTo(area.right(), area.bottom())
        fill.lineTo(area.left(), area.bottom())
        fill.closeSubpath()
        tint = QColor(theme.accent)
        tint.setAlpha(60)
        painter.fillPath(fill, tint)
        pen = QPen(theme.accent)
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.drawPath(path)

    def _paint_axes(self, painter: QPainter, plot: QRect, spectrum: QRect, theme: Theme) -> None:
        assert self.frame is not None
        painter.setPen(theme.secondary)
        font = painter.font()
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
        painter.setFont(font)
        top_db = self.top_db()
        db = 0.0
        while db <= top_db:
            y = spectrum.bottom() - db / top_db * spectrum.height()
            label = QRect(0, round(y) - 8, SCALE_WIDTH - 6, 16)
            painter.drawText(label, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{db:.0f} dB")  # fmt: skip
            db += DB_GRID
        low, high = self.frame.low_hz, self.frame.high_hz
        centre = (low + high) // 2
        y = plot.bottom() + 4
        width = 140
        painter.drawText(QRect(plot.left(), y, width, AXIS_HEIGHT - 4),
                         Qt.AlignmentFlag.AlignLeft, format_khz(low))  # fmt: skip
        painter.drawText(QRect(plot.center().x() - width // 2, y, width, AXIS_HEIGHT - 4),
                         Qt.AlignmentFlag.AlignHCenter, format_khz(centre))  # fmt: skip
        painter.drawText(QRect(plot.right() - width, y, width, AXIS_HEIGHT - 4),
                         Qt.AlignmentFlag.AlignRight, format_khz(high))  # fmt: skip
        marker = QPen(theme.secondary)
        marker.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(marker)
        painter.drawLine(plot.center().x(), plot.top(), plot.center().x(), spectrum.bottom())

    def axis_labels(self) -> tuple[str, str, str]:
        """Low, centre, and high frequency labels (for tests and accessibility)."""
        if self.frame is None:
            return ("", "", "")
        low, high = self.frame.low_hz, self.frame.high_hz
        return format_khz(low), format_khz((low + high) // 2), format_khz(high)
