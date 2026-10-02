# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from pathlib import Path

from cliutil import cli
from fakes import FakeApi
from frames import make_ft4222_frame

from n1mm_scope_bridge.transport.replay import CaptureReader, read_raw_stream


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


def test_record_raw_stream_keeps_every_read(tmp_path: Path) -> None:
    out = tmp_path / "raw.raw"
    misaligned = b"\x00" * 100 + make_ft4222_frame() * 4
    code, _, err = cli("record", "--raw-stream", "--frames", "2", str(out), api=FakeApi(misaligned))
    assert code == 0
    model, size, chunks = read_raw_stream(out)
    assert (model, size) == ("FT-710", 4096)
    assert b"".join(c.data for c in chunks).startswith(b"\x00" * 100)  # pre-alignment bytes kept
    assert "Recorded 2 frames" in err
    assert "raw reads" in err
