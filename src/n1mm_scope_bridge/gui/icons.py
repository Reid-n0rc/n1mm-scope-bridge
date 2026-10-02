# SPDX-License-Identifier: GPL-3.0-only AND ISC AND MIT
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
# SPDX-FileCopyrightText: 2026 Lucide Icons and Contributors
# SPDX-FileCopyrightText: 2013-present Cole Bemis
#
# Icon shapes below are from Lucide v1.49.0 (https://lucide.dev), ISC License:
#
#   Copyright (c) 2026 Lucide Icons and Contributors
#   Permission to use, copy, modify, and/or distribute this software for any
#   purpose with or without fee is hereby granted, provided that the above
#   copyright notice and this permission notice appear in all copies.
#   THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
#   WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
#   MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
#   SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER
#   RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF
#   CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN
#   CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#
# The icons chevron-down, chevron-up, info, square are derived from Feather, MIT License:
#   Copyright (c) 2013-present Cole Bemis. Permission is hereby granted, free of
#   charge, to any person obtaining a copy of this software, to deal in the
#   Software without restriction, subject to including this notice. THE SOFTWARE
#   IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
#
# Modified by Reid Crowe, N0RC, 2026-10-02: kept only the inner SVG elements;
# the stroke colour is filled in at run time from the current palette.
"""Line icons for the GUI, tinted from the palette so they work in light and dark."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

SOURCE = "Lucide v1.49.0"
SIZES = (16, 20, 24, 32, 48)

SHAPES: dict[str, str] = {
    "play": (
        '<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0'
        ' 1 5 19z"/>'
    ),
    "eye": (
        '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0'
        ' .696 10.75 10.75 0 0 1-19.876 0"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
    "eye-off": (
        '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747'
        ' 10.747 0 0 1-1.444 2.49"/>'
        '<path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/>'
        '<path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75'
        ' 10.75 0 0 1 4.446-5.143"/>'
        '<path d="m2 2 20 20"/>'
    ),
    "square": ('<rect width="18" height="18" x="3" y="3" rx="2"/>'),
    "settings": (
        '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34'
        " 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0"
        " 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0"
        " 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0"
        ' 3.319-1.915"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
    "ellipsis": (
        '<circle cx="12" cy="12" r="1"/>'
        '<circle cx="19" cy="12" r="1"/>'
        '<circle cx="5" cy="12" r="1"/>'
    ),
    "activity": (
        '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24'
        ' 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>'
    ),
    "circle-check": ('<circle cx="12" cy="12" r="10"/><path d="m16 9-5.5 5.5L8 12"/>'),
    "triangle-alert": (
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
        '<path d="M12 9v4"/>'
        '<path d="M12 17h.01"/>'
    ),
    "circle-x": ('<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>'),
    "copy": (
        '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>'
        '<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>'
    ),
    "book-open": (
        '<path d="M12 5v16"/>'
        '<path d="M20.001 19A2 2 0 0022 17V5a2 2 0 00-1.999-2L16 3.002A5 5 0 0012 5a5 5 0'
        ' 00-4-2H4a2 2 0 00-2 2v12a2 2 0 001.999 2H8a5 5 0 014 2 5 5 0 014-2z"/>'
    ),
    "info": ('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>'),
    "chevron-down": ('<path d="m6 9 6 6 6-6"/>'),
    "chevron-up": ('<path d="m18 15-6-6-6 6"/>'),
    "radio-tower": (
        '<path d="M4.9 16.1C1 12.2 1 5.8 4.9 1.9"/>'
        '<path d="M7.8 4.7a6.14 6.14 0 0 0-.8 7.5"/>'
        '<circle cx="12" cy="9" r="2"/>'
        '<path d="M16.2 4.8c2 2 2.26 5.11.8 7.47"/>'
        '<path d="M19.1 1.9a9.96 9.96 0 0 1 0 14.1"/>'
        '<path d="M9.5 18h5"/>'
        '<path d="m8 22 4-11 4 11"/>'
    ),
}


def svg(name: str, colour: QColor, stroke_width: float = 2.0) -> bytes:
    """A complete SVG document for ``name`` drawn in ``colour``."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{colour.name()}" stroke-width="{stroke_width}" stroke-linecap="round" '
        f'stroke-linejoin="round">{SHAPES[name]}</svg>'
    ).encode()


def pixmap(name: str, colour: QColor, size: int, ratio: float = 1.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg(name, colour)))
    device = max(1, round(size * ratio))
    image = QPixmap(device, device)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, device, device))
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image


def icon(name: str, colour: QColor) -> QIcon:
    """A multi-size icon tinted ``colour``."""
    result = QIcon()
    for size in SIZES:
        result.addPixmap(pixmap(name, colour, size))
    return result
