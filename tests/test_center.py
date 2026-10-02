# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import pytest

from n1mm_scope_bridge.center import CenterModeMonitor, format_macros, n1mm_macros, scope_mode_cat
from n1mm_scope_bridge.radios.base import ScopeStatus
from n1mm_scope_bridge.radios.yaesu_scope import YaesuScopeStatus


def st(family: str, name: str) -> ScopeStatus:
    return ScopeStatus(14_074_000, 20_000, family, name)  # type: ignore[arg-type]


CURSOR = st("cursor", "Cursor (Normal)")
CENTER = st("center", "Center (Normal)")


def run(*statuses: ScopeStatus) -> list[str]:
    messages: list[str] = []
    monitor = CenterModeMonitor("FT-710", messages.append)
    for status in statuses:
        monitor.observe(status)
    return messages


def test_prompts_then_confirms_once() -> None:
    messages = run(CURSOR, CURSOR, CENTER, CENTER)
    assert messages[0].startswith(
        "Set the FT-710's scope to Center mode for exact N1MM+ frequencies "
        "(currently Cursor (Normal)). Streaming continues meanwhile.\n"
    )
    assert messages[0].endswith("Scope Center,{CAT1ASC SS0640000;}")  # start mode unknown here
    assert messages[1:] == ["FT-710 scope is in Center mode: N1MM+ frequencies are exact."]


def test_silent_when_already_in_center() -> None:
    assert run(CENTER, CENTER) == []


def test_notices_leaving_center() -> None:
    messages = run(CENTER, CURSOR, CENTER)
    assert messages[0].startswith("FT-710 scope left Center mode (Cursor (Normal))")
    assert messages[1].startswith("FT-710 scope is in Center mode")


def test_unknown_mode_counts_as_not_center() -> None:
    assert (
        "(currently unknown (F)). Streaming continues meanwhile."
        in run(st("unknown", "unknown (F)"))[0]
    )


def test_macros_capture_restore_code_from_first_frame() -> None:
    messages: list[str] = []
    monitor = CenterModeMonitor("FT-710", messages.append)
    cursor = YaesuScopeStatus(14_074_000, 20_000, "cursor", "Cursor (Normal)", 0, 0, "7", 0)
    monitor.observe(cursor)
    assert monitor.start_code == "7"
    assert monitor.macros() == [
        ("Scope Center", "{CAT1ASC SS0640000;}"),
        ("Scope restore", "{CAT1ASC SS0670000;}"),
    ]
    assert messages[0].endswith(
        "Scope Center,{CAT1ASC SS0640000;}\nScope restore,{CAT1ASC SS0670000;}"
    )
    monitor.observe(CENTER)
    monitor.observe(CURSOR)  # second departure: no macros repeated
    assert "CAT1ASC" not in messages[-1]


def test_macros_without_known_start_mode() -> None:
    assert CenterModeMonitor("FT-710", print).macros() == [("Scope Center", "{CAT1ASC SS0640000;}")]
    assert n1mm_macros("4") == [("Scope Center", "{CAT1ASC SS0640000;}")]
    assert (
        format_macros(n1mm_macros("a"))
        == "Scope Center,{CAT1ASC SS0640000;}\nScope restore,{CAT1ASC SS06A0000;}"
    )


@pytest.mark.parametrize("bad", ["", "C", "44"])
def test_scope_mode_cat_rejects_bad_codes(bad: str) -> None:
    with pytest.raises(ValueError, match="scope mode code"):
        scope_mode_cat(bad)
