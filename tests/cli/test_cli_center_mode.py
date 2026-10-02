# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""``run --force-center-mode`` end to end against the emulator (#62)."""

from __future__ import annotations

import io

import pytest
from cliutil import FIXTURE, cli
from fakes import FakeApi
from frames import make_ft4222_frame

from n1mm_scope_bridge.cat import EmulatorCat, ScopeModeKeeper
from n1mm_scope_bridge.cli.session import StreamSession
from n1mm_scope_bridge.emulator import Ft710Emulator, RadioState
from n1mm_scope_bridge.settings import Settings
from n1mm_scope_bridge.transport.ft4222 import Ft4222Error, Ft4222Reader

SETTINGS = Settings(n1mm_port=9, rate_hz=10.0, force_center_mode=True)


def session_for(emu: Ft710Emulator, err: io.StringIO) -> tuple[StreamSession, list[str]]:
    sent: list[str] = []

    def make_source() -> tuple[Ft4222Reader, object]:
        reader = Ft4222Reader(emu)
        return reader, reader.stop

    def make_keeper(source: object) -> ScopeModeKeeper:
        cat = EmulatorCat(emu)
        original = cat.set_scope_mode

        def record(code: str) -> None:
            sent.append(code)
            original(code)

        cat.set_scope_mode = record  # type: ignore[method-assign]
        return ScopeModeKeeper(cat)

    return StreamSession(SETTINGS, make_source, err, make_keeper=make_keeper), sent  # type: ignore[arg-type]


def test_switches_to_center_and_restores_on_stop() -> None:
    emu = Ft710Emulator(RadioState(scope_mode=0x07), fps=200)
    session, sent = session_for(emu, io.StringIO())
    session.start()
    session.wait(duration=0.8)
    assert sent == ["4", "7"]
    assert emu.state.scope_mode == 0x07  # operator's Cursor mode is back


def test_restores_on_stream_error() -> None:
    emu = Ft710Emulator(RadioState(scope_mode=0x0A), fps=200)
    emu.faults.io_error_after_frames = 60
    session, sent = session_for(emu, io.StringIO())
    session.start()
    with pytest.raises(Ft4222Error):
        session.wait(duration=5)
    assert sent == ["4", "A"]
    assert emu.state.scope_mode == 0x0A


def test_cli_flag_with_emulator() -> None:
    code, _, err = cli(
        "run", "--emulator", "--force-center-mode", "--duration", "0.6", "--port", "9"
    )
    assert code == 0, err
    assert "not available" not in err


def test_cli_flag_with_real_radio_warns_and_continues() -> None:
    api = FakeApi(repeat=make_ft4222_frame())
    code, _, err = cli("run", "--force-center-mode", "--duration", "0.4", "--port", "9", api=api)
    assert code == 0
    assert "warning: force_center_mode is not available with a real radio yet" in err


def test_replay_ignores_force_center_mode() -> None:
    code, _, err = cli(
        "run", "--replay", str(FIXTURE), "--force-center-mode", "--duration", "0.3", "--port", "9"
    )
    assert code == 0
    assert "not available" in err


def test_off_by_default() -> None:
    assert Settings().force_center_mode is False
