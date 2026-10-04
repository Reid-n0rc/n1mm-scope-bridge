# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import pytest
from coverage_gate import AREAS, FLOORS, Report, check, main


def fake(values: dict[str, float | None]) -> Report:
    return {AREAS[k]: v for k, v in values.items()}.get


def test_floors_cover_every_area() -> None:
    assert set(FLOORS) == set(AREAS)
    assert FLOORS["app"] == 90.0


def test_all_above_floor() -> None:
    assert check(fake({"app": 99.6, "scripts": 98.0}), FLOORS) == []


def test_area_below_floor_is_reported() -> None:
    problems = check(fake({"app": 89.9, "scripts": 98.0}), FLOORS)
    assert problems == ["app: 89.9% is below the 90% floor"]


def test_missing_data_is_reported() -> None:
    problems = check(fake({"app": 99.0, "scripts": None}), FLOORS)
    assert problems == ["scripts: no coverage data (pattern */scripts/*)"]


def test_main_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([], report=fake({"app": 99.0, "scripts": 99.0})) == 0
    assert "OK" in capsys.readouterr().out
    assert main([], report=fake({"app": 50.0, "scripts": 99.0})) == 1
    assert "below the 90% floor" in capsys.readouterr().err
