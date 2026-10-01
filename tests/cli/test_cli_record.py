# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from pathlib import Path

from cliutil import cli
from fakes import FakeApi
from frames import make_ft4222_frame

from n1mm_scope_bridge.transport.replay import CaptureReader


def test_record_writes_capture(tmp_path: Path) -> None:
    out = tmp_path / "cap.cap"
    code, _, err = cli("record", "--frames", "3", str(out), api=FakeApi(make_ft4222_frame() * 5))
    assert code == 0
    assert len(list(CaptureReader(out))) == 3
    assert "Recorded 3 frames" in err


def test_record_rejects_zero_frames(tmp_path: Path) -> None:
    code, _, err = cli("record", "--frames", "0", str(tmp_path / "x.cap"), api=FakeApi())
    assert code == 1
    assert "--frames" in err


def test_record_from_emulator(tmp_path: Path) -> None:
    out = tmp_path / "emu.cap"
    code, _, _ = cli("record", "--scenario", "band-scan", "--frames", "3", str(out))
    assert code == 0
    assert len(list(CaptureReader(out))) == 3
