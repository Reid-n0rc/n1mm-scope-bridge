# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from cliutil import cli
from fakes import FakeApi
from frames import make_ft4222_frame


def test_probe_reports_radio_and_center_tip() -> None:
    code, out, _ = cli("probe", api=FakeApi(make_ft4222_frame(scope_mode=0x07)))
    assert code == 0
    assert "FTDI libraries loaded." in out
    assert "FT-710 found on 'FT4222 A'." in out
    assert "VFO-A 14074000 Hz" in out
    assert "Center mode" in out
    code, out, _ = cli("probe", api=FakeApi(make_ft4222_frame()))
    assert "Center mode" not in out


def test_probe_with_emulator_scenarios() -> None:
    code, out, _ = cli("probe", "--emulator")
    assert code == 0
    assert "Using the built-in FT-710 emulator." in out
    code, _, err = cli("probe", "--scenario", "not-connected")
    assert code == 1
    assert "Could not open" in err
