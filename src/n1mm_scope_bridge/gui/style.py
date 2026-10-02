# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The GUI design system: native style, theme tokens, and one stylesheet.

STYLE.md (GUI): ``windows11`` on Windows, ``Fusion`` elsewhere. Surface and
text colours come from the current ``QPalette`` (so light and dark both
work). The only fixed colours are the semantic status tokens below (success,
warning, danger), taken from Windows 11's Fluent design for light and dark,
and the waterfall colour map in ``spectrum.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

PREFERRED_STYLES = ("windows11", "Fusion")

# Fluent (Windows 11) InfoBar/status colours: (foreground, background).
SEMANTIC_LIGHT = {
    "success": ("#0f7b0f", "#dff6dd"),
    "warning": ("#8a5300", "#fff4ce"),
    "danger": ("#c42b1c", "#fde7e9"),
}
SEMANTIC_DARK = {
    "success": ("#6ccb5f", "#393d1b"),
    "warning": ("#fce100", "#433519"),
    "danger": ("#ff99a4", "#442726"),
}


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def mix(a: QColor, b: QColor, amount: float) -> QColor:
    """``a`` blended toward ``b`` by ``amount`` (0..1)."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * amount),
        round(a.green() + (b.green() - a.green()) * amount),
        round(a.blue() + (b.blue() - a.blue()) * amount),
    )


def accent(palette: QPalette) -> QColor:
    role = getattr(QPalette.ColorRole, "Accent", QPalette.ColorRole.Highlight)
    colour = palette.color(role)
    return colour if colour.isValid() else palette.color(QPalette.ColorRole.Highlight)


def on_colour(background: QColor) -> QColor:
    """Black or white, whichever reads better on ``background``."""
    return QColor("#000000") if relative_luminance(background) > 0.4 else QColor("#ffffff")


def relative_luminance(colour: QColor) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(colour.red())
        + 0.7152 * channel(colour.green())
        + 0.0722 * channel(colour.blue())
    )


def contrast(a: QColor, b: QColor) -> float:
    """WCAG contrast ratio between two colours."""
    hi, lo = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@dataclass(frozen=True)
class Theme:
    dark: bool
    window: QColor
    card: QColor
    border: QColor
    text: QColor
    secondary: QColor
    accent: QColor
    on_accent: QColor
    semantic: dict[str, tuple[QColor, QColor]]

    @classmethod
    def from_palette(cls, palette: QPalette) -> Theme:
        dark = is_dark(palette)
        window = palette.color(QPalette.ColorRole.Window)
        text = palette.color(QPalette.ColorRole.WindowText)
        white, black = QColor("#ffffff"), QColor("#000000")
        card = mix(window, white, 0.06) if dark else palette.color(QPalette.ColorRole.Base)
        if not dark and card == window:
            card = mix(window, white, 0.6)
        tokens = SEMANTIC_DARK if dark else SEMANTIC_LIGHT
        acc = accent(palette)
        return cls(
            dark=dark,
            window=window,
            card=card,
            border=mix(card, text if dark else black, 0.14 if dark else 0.12),
            text=text,
            secondary=mix(text, window, 0.38),
            accent=acc,
            on_accent=on_colour(acc),
            semantic={k: (QColor(fg), QColor(bg)) for k, (fg, bg) in tokens.items()},
        )

    def colour(self, kind: str) -> QColor:
        """Foreground colour for a status kind (success/warning/danger/neutral)."""
        if kind in self.semantic:
            return self.semantic[kind][0]
        return self.secondary


def build_stylesheet(theme: Theme) -> str:
    def c(colour: QColor) -> str:
        return colour.name()

    hover = mix(theme.accent, theme.on_accent, 0.12)
    pressed = mix(theme.accent, QColor("#000000"), 0.15)
    rules = [
        f"QWidget#root {{ background: {c(theme.window)}; }}",
        f"QFrame#card {{ background: {c(theme.card)}; border: 1px solid {c(theme.border)};"
        " border-radius: 8px; }",
        "QLabel#appTitle { font-size: 20px; font-weight: 600; }",
        f"QLabel#subtitle, QLabel#cardTitle, QLabel#cardDetail, QLabel#message,"
        f" QLabel#pageHint {{ color: {c(theme.secondary)}; }}",
        "QLabel#cardTitle { font-size: 12px; font-weight: 600; }",
        "QLabel#cardValue { font-size: 18px; font-weight: 600; }",
        "QLabel#pageTitle { font-size: 16px; font-weight: 600; }",
        f"QPushButton#primary {{ background: {c(theme.accent)}; color: {c(theme.on_accent)};"
        " border: none; border-radius: 6px; padding: 8px 20px; font-weight: 600;"
        " min-width: 96px; }",
        f"QPushButton#primary:hover {{ background: {c(hover)}; }}",
        f"QPushButton#primary:pressed {{ background: {c(pressed)}; }}",
        f'QPushButton#primary[running="true"] {{ background: {c(theme.card)};'
        f" color: {c(theme.text)}; border: 1px solid {c(theme.border)}; }}",
        "QToolButton#flat { border: none; padding: 6px; border-radius: 6px; }",
        "QToolButton#flat::menu-indicator { image: none; width: 0; }",
        f"QToolButton#flat:hover {{ background: {c(theme.border)}; }}",
        "QLabel#pill, QLabel#chip { border-radius: 11px; padding: 3px 12px; font-weight: 600; }",
        f'QLabel#pill[kind="neutral"], QLabel#chip[kind="neutral"] {{'
        f" color: {c(theme.secondary)}; border: 1px solid {c(theme.border)}; }}",
    ]
    for kind, (fg, bg) in theme.semantic.items():
        rules.append(
            f'QLabel#pill[kind="{kind}"], QLabel#chip[kind="{kind}"], QLabel#banner[kind="{kind}"]'
            f" {{ color: {c(fg)}; background: {c(bg)}; border: 1px solid {c(fg)}; }}"
        )
    danger = theme.semantic["danger"][0]
    rules += [
        "QLabel#banner { border-radius: 6px; padding: 8px 12px; }",
        f"QLabel#fieldError {{ color: {c(danger)}; font-weight: 600; }}",
        "QListWidget#sidebar { background: transparent; border: none; outline: none; }",
        "QListWidget#sidebar::item { padding: 0 12px; border-radius: 6px; }",
        f"QListWidget#sidebar::item:selected {{ background: {c(theme.border)};"
        f" color: {c(theme.text)}; }}",
        f"QPlainTextEdit#log {{ background: {c(theme.window)}; border: none; }}",
    ]
    return "\n".join(rules) + "\n"


def choose_style(available: Sequence[str]) -> str:
    """The first preferred style Qt offers (case-insensitive), else Fusion."""
    lowered = {name.lower(): name for name in available}
    for name in PREFERRED_STYLES:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return "Fusion"


def dark_palette() -> QPalette:
    """A dark palette for platforms that ignore a dark-scheme request (screenshots)."""
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: "#202020",
        QPalette.ColorRole.WindowText: "#ffffff",
        QPalette.ColorRole.Base: "#383838",
        QPalette.ColorRole.AlternateBase: "#2b2b2b",
        QPalette.ColorRole.Text: "#ffffff",
        QPalette.ColorRole.Button: "#2d2d2d",
        QPalette.ColorRole.ButtonText: "#ffffff",
        QPalette.ColorRole.Mid: "#3a3a3a",
        QPalette.ColorRole.Light: "#6b6b6b",
        QPalette.ColorRole.Midlight: "#4a4a4a",
        QPalette.ColorRole.Dark: "#141414",
        QPalette.ColorRole.Shadow: "#000000",
        QPalette.ColorRole.Highlight: "#4cc2ff",
        QPalette.ColorRole.HighlightedText: "#000000",
        QPalette.ColorRole.PlaceholderText: "#9d9d9d",
        QPalette.ColorRole.ToolTipBase: "#2b2b2b",
        QPalette.ColorRole.ToolTipText: "#ffffff",
    }
    accent_role = getattr(QPalette.ColorRole, "Accent", None)
    if accent_role is not None:
        roles[accent_role] = "#4cc2ff"
    for role, colour in roles.items():
        palette.setColor(role, QColor(colour))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#7a7a7a"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#7a7a7a"))
    return palette


def refresh_stylesheet(app: QApplication) -> Theme:
    """Rebuild the stylesheet from the current palette (call after a theme change)."""
    theme = Theme.from_palette(app.palette())
    app.setStyleSheet(build_stylesheet(theme))
    return theme


def apply_style(app: QApplication) -> str:
    style = choose_style(QStyleFactory.keys())
    app.setStyle(style)
    refresh_stylesheet(app)
    hints = app.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda _scheme: refresh_stylesheet(app))
    return style


__all__ = [
    "Theme",
    "apply_style",
    "build_stylesheet",
    "choose_style",
    "contrast",
    "dark_palette",
    "refresh_stylesheet",
]
