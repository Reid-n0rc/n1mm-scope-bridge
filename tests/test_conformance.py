# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Conformance helpers (#36), exercised on emulator-generated raw captures."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from frames import make_ft4222_frame

from n1mm_scope_bridge.emulator import Faults, Ft710Emulator, RadioState
from n1mm_scope_bridge.emulator import conformance as cf
from n1mm_scope_bridge.radios import yaesu_scope as ys
from n1mm_scope_bridge.transport.ft4222 import Ft4222Reader
from n1mm_scope_bridge.transport.replay import (
    RawChunk,
    RawStreamWriter,
    RecordingApi,
    read_raw_stream,
)


def raw_capture(
    tmp_path: Path, emu: Ft710Emulator, frames: int = 6, fps: float = 20.0
) -> list[RawChunk]:
    """Record a raw capture from ``emu`` with a fake clock ticking at ``fps``."""
    now = [0.0]

    def clock() -> float:
        now[0] += 1.0 / fps  # one tick per SPI read; aligned reads are one frame each
        return now[0]

    buf = io.BytesIO()
    reader = Ft4222Reader(RecordingApi(emu, RawStreamWriter(buf, "FT-710", 4096, clock=clock)))
    for n, _ in enumerate(reader, 1):
        if n >= frames:
            reader.stop()
    path = tmp_path / "c.raw"
    path.write_bytes(buf.getvalue())
    return read_raw_stream(path)[2]


def test_emulator_conforms_to_itself(tmp_path: Path) -> None:
    chunks = raw_capture(tmp_path, Ft710Emulator(RadioState(span_index=6)))
    assert cf.compare(chunks, emulator_fps=20.0) == []


@pytest.mark.parametrize("padding", ["sync", "zero"])
def test_padding_style_detected(padding: str) -> None:
    emu = Ft710Emulator(padding=padding)  # type: ignore[arg-type]
    reader = Ft4222Reader(emu)
    reader.open()
    frame = reader.read_frame()
    assert frame is not None
    assert cf.padding_style(frame) == padding


def test_padding_style_other() -> None:
    frame = bytearray(make_ft4222_frame())
    frame[ys.FRAME_SIZE - 20] = 0x55
    assert cf.padding_style(bytes(frame)) == "other"


def test_padding_mismatch_is_reported(tmp_path: Path) -> None:
    chunks = raw_capture(tmp_path, Ft710Emulator(padding="zero"))
    problems = cf.compare(chunks, emulator_fps=20.0, emulator_padding="sync")
    assert problems == ["real frames use 'zero' padding, emulator uses 'sync'"]


def test_frame_rate_mismatch_is_reported(tmp_path: Path) -> None:
    chunks = raw_capture(tmp_path, Ft710Emulator(), fps=15.0)
    assert any(
        p.startswith("frame rate: radio 15.0/s") for p in cf.compare(chunks, emulator_fps=20.0)
    )


def test_misaligned_start_still_decodes(tmp_path: Path) -> None:
    chunks = raw_capture(tmp_path, Ft710Emulator(faults=Faults(start_offset=1234)))
    decoded = cf.decode_frames(chunks)
    assert decoded.frames
    assert decoded.resyncs >= 1


def test_empty_capture() -> None:
    assert cf.compare([], emulator_fps=20.0) == ["no whole frames in the capture"]
    assert cf.measured_fps([]) is None


def test_status_mismatch_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = raw_capture(tmp_path, Ft710Emulator())
    real_like = cf.emulator_like

    def shifted(frame: bytes, **kw: object) -> Ft710Emulator:
        emu = real_like(frame, **kw)  # type: ignore[arg-type]
        emu.tune(7_074_000)
        return emu

    monkeypatch.setattr(cf, "emulator_like", shifted)
    problems = cf.compare(chunks, emulator_fps=20.0)
    assert any(p.startswith("vfo_hz: radio 14074000, emulator 7074000") for p in problems)


def test_noise_floor_mismatch_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = raw_capture(tmp_path, Ft710Emulator())
    floors = iter([200, 25])  # radio first, then emulator
    monkeypatch.setattr(cf, "noise_floor", lambda levels: next(floors))
    problems = cf.compare(chunks, emulator_fps=20.0)
    assert "noise floor: radio 200, emulator 25" in problems


def test_noise_floor_is_tenth_percentile() -> None:
    assert cf.noise_floor(tuple(range(100))) == 10


def test_emulator_like_reads_tx_flag() -> None:
    emu = Ft710Emulator()
    emu.set_tx(True)
    reader = Ft4222Reader(emu)
    reader.open()
    frame = reader.read_frame()
    assert frame is not None
    assert cf.emulator_like(frame).state.tx is True
