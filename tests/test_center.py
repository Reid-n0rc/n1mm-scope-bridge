# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from n1mm_scope_bridge.center import CenterModeMonitor
from n1mm_scope_bridge.radios.base import ScopeStatus


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
    assert messages == [
        "Set the FT-710's scope to Center mode for exact N1MM+ frequencies "
        "(currently Cursor (Normal)). Streaming continues meanwhile.",
        "FT-710 scope is in Center mode: N1MM+ frequencies are exact.",
    ]


def test_silent_when_already_in_center() -> None:
    assert run(CENTER, CENTER) == []


def test_notices_leaving_center() -> None:
    messages = run(CENTER, CURSOR, CENTER)
    assert messages[0].startswith("FT-710 scope left Center mode (Cursor (Normal))")
    assert messages[1].startswith("FT-710 scope is in Center mode")


def test_unknown_mode_counts_as_not_center() -> None:
    assert run(st("unknown", "unknown (F)"))[0].endswith(
        "(currently unknown (F)). Streaming continues meanwhile."
    )
