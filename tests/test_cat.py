# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import pytest

from n1mm_scope_bridge.cat import CENTER, EmulatorCat, ScopeModeKeeper, scope_mode_command
from n1mm_scope_bridge.emulator import Ft710Emulator
from n1mm_scope_bridge.radios.base import ScopeStatus
from n1mm_scope_bridge.radios.yaesu_scope import YaesuScopeStatus


def st(code: str) -> YaesuScopeStatus:
    return YaesuScopeStatus(14_074_000, 20_000, "center", "x", 7_074_000, 0, code, 0)


class Cat:
    def __init__(self, fail: Exception | None = None) -> None:
        self.sent: list[str] = []
        self.fail = fail

    def set_scope_mode(self, code: str) -> None:
        if self.fail:
            raise self.fail
        self.sent.append(code)


@pytest.mark.parametrize(
    ("code", "cmd"), [("4", "SS0640000;"), ("a", "SS06A0000;"), ("0", "SS0600000;")]
)
def test_scope_mode_command(code: str, cmd: str) -> None:
    assert scope_mode_command(code) == cmd


@pytest.mark.parametrize("bad", ["", "C", "44", "x"])
def test_scope_mode_command_rejects_bad_codes(bad: str) -> None:
    with pytest.raises(ValueError, match="scope mode code"):
        scope_mode_command(bad)


def test_sets_center_and_restores_previous_mode() -> None:
    cat = Cat()
    k = ScopeModeKeeper(cat)
    k.observe(st("7"))  # Cursor (Normal)
    k.observe(st("7"))  # radio hasn't applied it yet: not a manual change
    k.observe(st(CENTER))
    k.observe(st(CENTER))
    k.restore()
    assert cat.sent == [CENTER, "7"]
    k.restore()  # only once
    assert cat.sent == [CENTER, "7"]


def test_already_center_changes_nothing() -> None:
    cat = Cat()
    k = ScopeModeKeeper(cat)
    k.observe(st(CENTER))
    k.restore()
    assert cat.sent == []


def test_never_fights_a_manual_change() -> None:
    cat = Cat()
    k = ScopeModeKeeper(cat)
    k.observe(st("A"))
    k.observe(st(CENTER))
    k.observe(st("7"))  # operator picked Cursor after we set Center
    k.observe(st(CENTER))
    k.restore()
    assert cat.sent == [CENTER]  # no re-set, no restore over the operator's choice
    assert k.abandoned


def test_cat_failure_warns_and_stops_managing() -> None:
    warnings: list[str] = []
    k = ScopeModeKeeper(Cat(fail=OSError("port busy")), warn=warnings.append)
    k.observe(st("7"))
    k.restore()
    assert warnings == ["Could not change the scope mode (port busy); leaving it as it is."]
    assert not k.set_by_us


def test_status_without_mode_code_is_ignored() -> None:
    cat = Cat()
    k = ScopeModeKeeper(cat)
    k.observe(ScopeStatus(1, 2, "center", "x"))
    assert k.original is None
    assert cat.sent == []


def test_emulator_cat_applies_mode() -> None:
    emu = Ft710Emulator()
    cat = EmulatorCat(emu)
    cat.set_scope_mode("A")
    assert emu.state.scope_mode == 0x0A
    assert cat.commands == ["SS06A0000;"]
