# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Design system: theme tokens, contrast, icons, cards, badges, settings dialog."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="GUI needs PySide6 (not available on free-threaded Python)")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from n1mm_scope_bridge.gui import icons
from n1mm_scope_bridge.gui import style as st
from n1mm_scope_bridge.gui.settings_dialog import PAGES, STREAM_PAGES, SettingsDialog
from n1mm_scope_bridge.gui.widgets import Badge, Card

pytestmark = pytest.mark.gui


def light_palette() -> QPalette:
    palette = QPalette()
    for role, colour in {
        QPalette.ColorRole.Window: "#f3f3f3",
        QPalette.ColorRole.WindowText: "#1a1a1a",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.Highlight: "#0067c0",
    }.items():
        palette.setColor(role, QColor(colour))
    return palette


@pytest.mark.parametrize("palette", [light_palette(), st.dark_palette()], ids=["light", "dark"])
def test_theme_text_meets_wcag_aa(palette: QPalette) -> None:
    theme = st.Theme.from_palette(palette)
    assert st.contrast(theme.text, theme.card) >= 4.5
    assert st.contrast(theme.secondary, theme.card) >= 4.5
    assert st.contrast(theme.on_accent, theme.accent) >= 4.5 or theme.on_accent.name() in (
        "#000000",
        "#ffffff",
    )
    for kind, (fg, bg) in theme.semantic.items():
        assert st.contrast(fg, bg) >= 4.5, kind


def test_theme_detects_dark_and_builds_stylesheet() -> None:
    dark = st.Theme.from_palette(st.dark_palette())
    light = st.Theme.from_palette(light_palette())
    assert dark.dark
    assert not light.dark
    sheet = st.build_stylesheet(dark)
    assert dark.accent.name() in sheet
    assert 'QLabel#pill[kind="danger"]' in sheet
    assert dark.colour("success") == dark.semantic["success"][0]
    assert dark.colour("neutral") == dark.secondary


def test_colour_helpers() -> None:
    assert st.mix(QColor("#000000"), QColor("#ffffff"), 0.5).name() == "#808080"
    assert st.on_colour(QColor("#ffffff")).name() == "#000000"
    assert st.on_colour(QColor("#0067c0")).name() == "#ffffff"
    assert round(st.contrast(QColor("#000000"), QColor("#ffffff")), 1) == 21.0


def test_refresh_stylesheet_follows_palette(qapp: QApplication) -> None:
    original = qapp.palette()
    try:
        qapp.setPalette(st.dark_palette())
        theme = st.refresh_stylesheet(qapp)
        assert theme.dark
        assert theme.card.name() in qapp.styleSheet()
    finally:
        qapp.setPalette(original)
        st.refresh_stylesheet(qapp)


@pytest.mark.parametrize("name", sorted(icons.SHAPES))
def test_every_icon_renders_in_the_requested_colour(qapp: QApplication, name: str) -> None:
    image = icons.pixmap(name, QColor("#ff0000"), 24).toImage()
    painted = [
        image.pixelColor(x, y) for x in range(24) for y in range(24)
        if image.pixelColor(x, y).alpha() > 200
    ]  # fmt: skip
    assert painted, name
    assert all(c.red() > 200 and c.green() < 60 for c in painted)
    assert not icons.icon(name, QColor("#00ff00")).isNull()


def test_badge_and_card(qtbot: QtBot) -> None:
    badge = Badge("Streaming", role="pill")
    qtbot.addWidget(badge)
    assert badge.objectName() == "pill"
    badge.set_kind("success")
    assert badge.kind == "success"
    with pytest.raises(ValueError, match="unknown badge kind"):
        badge.set_kind("purple")
    card = Card("Frequency", monospace=True)
    qtbot.addWidget(card)
    card.show()
    assert card.value.text() == "—"
    card.show_chip("✓ Exact frequencies", "success")
    assert card.chip.isVisible()
    assert card.chip.kind == "success"
    card.show_chip("", "neutral")
    assert not card.chip.isVisible()


def test_settings_dialog_pages_and_lock(qtbot: QtBot) -> None:
    browsed: list[bool] = []
    dialog = SettingsDialog(lambda: browsed.append(True))
    qtbot.addWidget(dialog)
    assert [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())] == list(PAGES)
    dialog.show_page("Display")
    assert dialog.stack.currentWidget() is dialog.pages["Display"]
    dialog.browse.click()
    assert browsed == [True]
    assert [dialog.combine.itemText(i) for i in range(3)] == ["Off", "Average", "Peak hold"]
    dialog.set_streaming(True)
    for name in PAGES:
        locked = name in STREAM_PAGES
        assert dialog.pages[name].fields.isEnabled() is not locked
        assert dialog.pages[name].locked.isVisibleTo(dialog.pages[name]) is locked
    dialog.set_streaming(False)
    assert all(page.fields.isEnabled() for page in dialog.pages.values())
    assert set(dialog.errors) >= {"radio", "n1mm_host", "n1mm_port", "rate_hz", "device"}
