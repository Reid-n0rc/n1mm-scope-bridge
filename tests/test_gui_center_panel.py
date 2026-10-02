# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip("PySide6", reason="GUI needs PySide6 (not available on free-threaded Python)")

from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from n1mm_scope_bridge.gui.center_panel import CenterModePanel
from n1mm_scope_bridge.radios.base import ScopeStatus

pytestmark = pytest.mark.gui


@dataclass(frozen=True)
class CodedStatus(ScopeStatus):
    scope_mode_code: str = "4"


CENTER = CodedStatus(7_074_000, 10_000, "center", "Center (Normal)", "4")
CURSOR = CodedStatus(7_074_000, 10_000, "cursor", "Cursor (Normal)", "7")
FIXED = CodedStatus(7_074_000, 10_000, "fixed", "Fixed (Normal)", "A")


def make(qtbot: QtBot, **kw: object) -> tuple[CenterModePanel, list[str]]:
    logged: list[str] = []
    panel = CenterModePanel("FT-710", log=logged.append, **kw)  # type: ignore[arg-type]
    qtbot.addWidget(panel)
    panel.show()
    panel.hide()
    return panel, logged


def test_hidden_while_in_center(qtbot: QtBot) -> None:
    panel, logged = make(qtbot)
    panel.observe(CENTER)
    assert not panel.isVisible()
    assert logged == []


def test_prompt_with_center_and_restore_macros(qtbot: QtBot) -> None:
    panel, logged = make(qtbot)
    panel.observe(CURSOR)
    assert panel.isVisible()
    assert "Cursor (Normal)" in panel.message.text()
    assert "never does" in panel.message.text()
    assert panel.badge.kind == "warning"
    assert list(panel.macro_fields) == ["Scope Center", "Scope restore"]
    assert panel.macro_fields["Scope Center"].text() == "Scope Center,{CAT1ASC SS0640000;}"
    assert panel.macro_fields["Scope restore"].text() == "Scope restore,{CAT1ASC SS0670000;}"
    assert panel.macro_fields["Scope Center"].isReadOnly()
    assert logged  # the monitor's prompt goes to the activity log too


def test_no_restore_macro_when_stream_started_in_center(qtbot: QtBot) -> None:
    panel, _ = make(qtbot)
    panel.observe(CENTER)
    panel.observe(FIXED)
    assert list(panel.macro_fields) == ["Scope Center"]


def test_copy_button_copies_macro_text(qtbot: QtBot) -> None:
    panel, _ = make(qtbot)
    panel.observe(CURSOR)
    QApplication.clipboard().clear()
    panel.copy_buttons["Scope Center"].click()
    assert QApplication.clipboard().text() == "Scope Center,{CAT1ASC SS0640000;}"
    assert panel.copy_buttons["Scope Center"].text() == "Copied"
    qtbot.waitUntil(lambda: panel.copy_buttons["Scope Center"].text() == "Copy", timeout=3000)


def test_confirms_then_hides_when_center_is_reached(qtbot: QtBot) -> None:
    panel, _ = make(qtbot, confirm_ms=50)
    panel.observe(CURSOR)
    panel.observe(CENTER)
    assert panel.isVisible()
    assert panel.badge.kind == "success"
    assert "Center mode" in panel.message.text()
    assert not panel.macro_box.isVisible()
    qtbot.waitUntil(lambda: not panel.isVisible(), timeout=2000)


def test_dismiss_until_mode_changes(qtbot: QtBot) -> None:
    panel, _ = make(qtbot)
    panel.observe(CURSOR)
    panel.dismiss.click()
    assert not panel.isVisible()
    panel.observe(CURSOR)
    assert not panel.isVisible()
    panel.observe(FIXED)
    assert panel.isVisible()
    assert "Fixed (Normal)" in panel.message.text()


def test_macros_are_rebuilt_without_duplicates(qtbot: QtBot) -> None:
    panel, _ = make(qtbot)
    panel.observe(CURSOR)
    panel.observe(FIXED)
    assert panel.macro_grid.count() == 6  # 2 macros x (label, field, button)


def test_reset_forgets_previous_stream(qtbot: QtBot) -> None:
    panel, _ = make(qtbot)
    panel.observe(CURSOR)
    panel.dismiss.click()
    panel.reset("FTDX10")
    assert not panel.isVisible()
    panel.observe(CURSOR)
    assert panel.isVisible()
    assert "FTDX10" in panel.message.text()
    panel.reset()
    assert panel.monitor.start_code is None
