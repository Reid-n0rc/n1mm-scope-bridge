# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="GUI needs PySide6 (not available on free-threaded Python)")

from pytestqt.qtbot import QtBot

from n1mm_scope_bridge.gui import spectrum as sp
from n1mm_scope_bridge.spectrum import SpectrumFrame

pytestmark = pytest.mark.gui


def frame(levels: tuple[int, ...], low: int = 14_064_000, high: int = 14_084_000) -> SpectrumFrame:
    return SpectrumFrame(low, high, levels, 255)


def test_colour_map_runs_dark_to_bright() -> None:
    lut = sp.colour_map()
    assert len(lut) == 256
    assert all(value >> 24 == 0xFF for value in lut)  # opaque

    def brightness(argb: int) -> int:
        return ((argb >> 16) & 0xFF) + ((argb >> 8) & 0xFF) + (argb & 0xFF)

    assert brightness(lut[0]) < brightness(lut[180])


def test_idle_shows_placeholder_and_no_axes(qtbot: QtBot) -> None:
    view = sp.SpectrumView()
    qtbot.addWidget(view)
    view.resize(600, 300)
    image = view.grab().toImage()
    assert not image.isNull()
    assert view.axis_labels() == ("", "", "")
    assert view.waterfall_row(0) == []
    assert view.top_db() == sp.MIN_TOP_DB


def test_set_frame_labels_edges_and_scrolls_waterfall(qtbot: QtBot) -> None:
    view = sp.SpectrumView()
    qtbot.addWidget(view)
    view.resize(600, 300)
    quiet = frame((10,) * 850)
    loud = frame((10,) * 400 + (250,) * 50 + (10,) * 400)
    view.set_frame(quiet, 0.3125)
    view.set_frame(loud, 0.3125)
    assert view.axis_labels() == ("14 064.0 kHz", "14 074.0 kHz", "14 084.0 kHz")
    assert view.rows_added == 2
    newest, older = view.waterfall_row(0), view.waterfall_row(1)
    assert newest[420] == sp.LUT[250 * 255 // 255]
    assert older[420] == sp.LUT[10 * 255 // 255]
    assert not view.grab().toImage().isNull()


def test_waterfall_wraps_after_history(qtbot: QtBot) -> None:
    view = sp.SpectrumView()
    qtbot.addWidget(view)
    for i in range(sp.HISTORY_ROWS + 5):
        view.set_frame(frame((i % 256,) * 8), 1.0)
    assert view.waterfall_row(0)[0] == sp.LUT[(sp.HISTORY_ROWS + 4) % 256]
    assert view.waterfall_row(sp.HISTORY_ROWS - 1)[0] == sp.LUT[5]
    view.grab()


def test_retune_restarts_waterfall_and_clear_resets(qtbot: QtBot) -> None:
    view = sp.SpectrumView()
    qtbot.addWidget(view)
    view.set_frame(frame((100,) * 8), 1.0)
    view.set_frame(frame((100,) * 8, low=7_000_000, high=7_020_000), 1.0)
    assert view.waterfall_row(1)[0] == sp.LUT[0]  # history from the old span is gone
    view.clear()
    assert view.frame is None
    assert view.rows_added == 0


def test_level_scale_adapts_to_recent_peaks(qtbot: QtBot) -> None:
    view = sp.SpectrumView()
    qtbot.addWidget(view)
    view.set_frame(frame((40,) * 8), 0.3125)  # 12.5 dB peak
    assert view.top_db() == sp.MIN_TOP_DB
    view.set_frame(frame((200,) * 8), 0.3125)  # 62.5 dB peak
    assert view.top_db() == 79.6875  # capped at the full scale (255 * 0.3125)
    view.set_frame(frame((150,) * 8), 0.3125)
    assert view.top_db() == 79.6875  # remembers the recent peak


def test_size_hint_is_landscape(qtbot: QtBot) -> None:
    view = sp.SpectrumView()
    qtbot.addWidget(view)
    hint = view.sizeHint()
    assert hint.width() > hint.height()
