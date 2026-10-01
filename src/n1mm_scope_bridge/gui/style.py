# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Application look: native modern style, system light/dark, no hard-coded colours.

STYLE.md (GUI): ``windows11`` on Windows, ``Fusion`` elsewhere; colours only
through palette references so both themes work.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QApplication, QStyleFactory

PREFERRED_STYLES = ("windows11", "Fusion")

# Palette references only; Qt resolves them for the current light/dark theme.
STYLESHEET = """
QLabel#statusChip {
    border-radius: 9px;
    padding: 2px 12px;
    border: 1px solid palette(mid);
}
QLabel#statusChip[state="streaming"] {
    background: palette(highlight);
    color: palette(highlighted-text);
    border-color: palette(highlight);
}
QLabel#statusChip[state="error"] {
    border: 2px solid palette(highlight);
    font-weight: 600;
}
QLabel#fieldError {
    font-weight: 600;
}
QPushButton#primary {
    padding: 6px 18px;
    font-weight: 600;
}
"""


def choose_style(available: Sequence[str]) -> str:
    """The first preferred style Qt offers (case-insensitive), else Fusion."""
    lowered = {name.lower(): name for name in available}
    for name in PREFERRED_STYLES:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return "Fusion"


def apply_style(app: QApplication) -> str:
    style = choose_style(QStyleFactory.keys())
    app.setStyle(style)
    app.setStyleSheet(STYLESHEET)
    return style
