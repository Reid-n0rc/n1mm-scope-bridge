# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The emulator must behave like the real FT-710 in the golden captures (#36).

Golden captures are recorded once at the radio with scripts/capture_golden.py
and committed to tests/fixtures/golden/. Until they exist, every test here is
an expected failure ("awaiting golden capture (#36)"), so CI shows the gap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from capture_golden import GOLDEN_DIR, PARSER_FILE, git_blob_hash

from n1mm_scope_bridge.cli.common import EMULATOR_FPS
from n1mm_scope_bridge.emulator import conformance as cf
from n1mm_scope_bridge.emulator.ft710 import Ft710Emulator
from n1mm_scope_bridge.transport.replay import read_raw_stream

MANIFEST = GOLDEN_DIR / "manifest.json"
STEADY = ("center-span-", "cursor-mode", "fixed-mode")


def _load() -> dict[str, Any] | None:
    if not MANIFEST.exists():
        return None
    data: dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return None if data.get("dry_run") else data


GOLDEN = _load()
CASES = [c for c in (GOLDEN or {}).get("cases", []) if c.get("file")]

if not CASES:
    pytestmark = pytest.mark.xfail(strict=True, reason="awaiting golden capture (#36)")


def test_golden_captures_exist() -> None:
    assert CASES, "record them at the radio: see docs/emulator.md, Validating against your radio"


def test_golden_captures_match_current_parser() -> None:
    """Changing the parser means re-validating against the radio."""
    assert GOLDEN is not None
    assert GOLDEN["validated_against"] == git_blob_hash(PARSER_FILE), (
        "radios/yaesu_scope.py changed since the golden captures were recorded; "
        "re-run scripts/capture_golden.py at the radio (#36)"
    )


def test_operator_confirmed_every_case() -> None:
    assert CASES
    unconfirmed = [c["name"] for c in CASES if not c.get("confirmed")]
    assert not unconfirmed, f"cases the operator did not confirm: {unconfirmed}"


@pytest.mark.parametrize("case", CASES or [{"name": "none", "file": ""}], ids=lambda c: c["name"])
def test_emulator_matches_radio(case: dict[str, Any]) -> None:
    _, _, chunks = read_raw_stream(GOLDEN_DIR / case["file"])
    if case["name"].startswith(STEADY):
        assert cf.compare(chunks, emulator_fps=EMULATOR_FPS, emulator_padding=_padding()) == []
    else:  # start-up, re-plug, transmit: the reader must recover and decode frames
        assert cf.decode_frames(chunks).frames


def _padding() -> cf.Padding:
    style: cf.Padding = Ft710Emulator().padding
    return style


def test_fixtures_are_small() -> None:
    assert CASES
    for case in CASES:
        assert (GOLDEN_DIR / case["file"]).stat().st_size <= 256 * 1024, case["name"]
    assert Path(GOLDEN_DIR).is_dir()
