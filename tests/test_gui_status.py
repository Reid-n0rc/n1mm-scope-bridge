# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Status presenter, log, and diagnostics (#28)."""

from __future__ import annotations

import json
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

import pytest

from n1mm_scope_bridge.gui.status import (
    DIAGNOSTIC_LOG_LINES,
    LogBuffer,
    StatusModel,
    diagnostics,
    redact_home,
)
from n1mm_scope_bridge.pipeline import PipelineStats
from n1mm_scope_bridge.radios.base import ScopeStatus
from n1mm_scope_bridge.settings import Settings

CENTER = ScopeStatus(14_074_000, 20_000, "center", "Center (Normal)")
CURSOR = ScopeStatus(7_074_000, 100_000, "cursor", "Cursor (Normal)")


def stats(emitted: int, read: int = 100) -> PipelineStats:
    return PipelineStats(frames_read=read, frames_dropped=1, bad_frames=2, emitted=emitted)


def test_idle_rows() -> None:
    rows = dict(StatusModel().rows())
    assert rows["Radio"] == "Not streaming"
    assert rows["VFO"] == "—"
    assert rows["Last error"] == "None"


def test_streaming_rows_and_rate() -> None:
    now = [10.0]
    model = StatusModel(clock=lambda: now[0])
    model.started()
    assert dict(model.rows())["Radio"] == "Waiting for the radio"
    model.update_stats(stats(0))
    now[0] = 12.0
    model.update_stats(stats(8))
    model.status = CENTER
    rows = dict(model.rows())
    assert rows["Radio"] == "Receiving scope data"
    assert rows["VFO"] == "14.074000 MHz"
    assert rows["Span"] == "20 kHz"
    assert rows["Scope mode"] == "Center (Normal)"
    assert rows["Sent to N1MM+"] == "4.0 per second (8 total)"
    assert rows["Dropped / bad frames"] == "1 / 2"
    assert model.summary("FT-710") == "Streaming FT-710 to N1MM+, 4.0 per second"


def test_rate_ignores_non_advancing_clock() -> None:
    model = StatusModel(clock=lambda: 5.0)
    model.update_stats(stats(1))
    model.update_stats(stats(9))
    assert model.rate_per_s == 0.0


def test_non_center_mode_hint() -> None:
    model = StatusModel()
    model.status = CURSOR
    assert dict(model.rows())["Scope mode"] == "Cursor (Normal) (set Center for exact frequencies)"


def test_stop_with_error_and_restart() -> None:
    model = StatusModel()
    model.started()
    model.stopped("No valid scope frames")
    assert dict(model.rows())["Last error"] == "No valid scope frames"
    assert model.summary("FT-710") == "Stopped (No valid scope frames)"
    model.stopped("")
    assert model.last_error == "No valid scope frames"  # kept until the next start
    model.started()
    assert model.last_error == ""
    model.stopped("")
    assert model.summary("FT-710") == "Stopped"


def test_log_buffer_is_bounded_and_timestamped() -> None:
    log = LogBuffer(limit=3, now=lambda: 0.0)
    for i in range(5):
        line = log.add("info", f"m{i}")
    assert line.endswith("info: m4")
    assert [ln.split(" ", 1)[1] for ln in log.lines()] == ["info: m2", "info: m3", "info: m4"]


@pytest.mark.parametrize(
    ("home", "text", "expected"),
    [
        (PurePosixPath("/Users/op"), "/Users/op/ftdi and /Users/op", "~/ftdi and ~"),
        (PureWindowsPath("C:/Users/op"), r"C:\Users\op\ftdi", r"~\ftdi"),
        (PureWindowsPath("C:/Users/op"), r'"C:\\Users\\op\\ftdi"', r'"~\\ftdi"'),
        (PureWindowsPath("C:/Users/op"), "C:/Users/op/ftdi", "~/ftdi"),
        (PurePosixPath("/"), "/x", "/x"),
    ],
)
def test_redact_home(home: PurePath, text: str, expected: str) -> None:
    assert redact_home(text, home) == expected


def test_redact_home_defaults_to_current_user() -> None:
    assert redact_home(str(Path.home()) + "/x") == "~/x"


def test_diagnostics_content(tmp_path: Path) -> None:
    settings = Settings(ftdi_lib_dir=str(tmp_path / "ftdi"), source_name="Shack")
    model = StatusModel()
    model.started()
    model.update_stats(stats(3, read=42))
    model.status = CENTER
    log = LogBuffer()
    for i in range(DIAGNOSTIC_LOG_LINES + 5):
        log.add("info", f"line {i}")
    text = diagnostics(settings, model, log, home=tmp_path)
    assert text.startswith("n1mm-scope-bridge ")
    assert str(tmp_path) not in text
    ftdi = json.loads(text.split("Settings:\n", 1)[1].split("\n\nStatus:", 1)[0])["ftdi_lib_dir"]
    assert ftdi.startswith("~")
    assert ftdi.endswith("ftdi")
    assert "VFO: 14.074000 MHz" in text
    assert "Frames read: 42" in text
    log_part = text.split("Log (last")[1].splitlines()[1:]
    assert len(log_part) == DIAGNOSTIC_LOG_LINES  # only the most recent lines
    assert log_part[0].endswith("info: line 5")
    assert f"line {DIAGNOSTIC_LOG_LINES + 4}" in text
    settings_json = text.split("Settings:\n", 1)[1].split("\n\nStatus:", 1)[0]
    assert json.loads(settings_json)["source_name"] == "Shack"


def test_diagnostics_without_stats() -> None:
    assert "Frames read: 0" in diagnostics(Settings(), StatusModel(), LogBuffer())
