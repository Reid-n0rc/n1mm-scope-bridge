# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import io
import threading
from pathlib import Path

import pytest

from n1mm_scope_bridge.transport.replay import (
    CaptureError,
    CaptureReader,
    CaptureWriter,
    format_header,
    parse_header,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ft710_synthetic.cap"


def write_capture(path: Path, frames: list[bytes], size: int = 4, tail: bytes = b"") -> Path:
    buf = io.BytesIO()
    writer = CaptureWriter(buf, "FT-710", size)
    for f in frames:
        writer.write(f)
    path.write_bytes(buf.getvalue() + tail)
    return path


def test_header_round_trip() -> None:
    assert parse_header(format_header("FT-710", 4096)) == ("FT-710", 4096)


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (b"garbage", "bad header"),
        (b"\xff\xfe", "bad header"),
        (b"N1MMSB1 FT-710 abc\n", "bad header"),
        (b"N1MMSB9 FT-710 4096\n", "unsupported"),
        (b"N1MMSB1 FT-710 0\n", "frame size"),
        (b"N1MMSB1 FT/710 4096\n", "model"),
    ],
)
def test_bad_headers(line: bytes, message: str) -> None:
    with pytest.raises(CaptureError, match=message):
        parse_header(line)


def test_writer_counts_and_rejects_wrong_size() -> None:
    writer = CaptureWriter(io.BytesIO(), "FT-710", 4)
    writer.write(b"abcd")
    assert writer.frames == 1
    with pytest.raises(CaptureError, match="expected 4"):
        writer.write(b"abc")


def test_reader_yields_frames(tmp_path: Path) -> None:
    path = write_capture(tmp_path / "c.cap", [b"aaaa", b"bbbb"])
    reader = CaptureReader(path)
    assert (reader.model, reader.frame_size) == ("FT-710", 4)
    assert list(reader) == [b"aaaa", b"bbbb"]


def test_reader_rejects_partial_trailing_frame(tmp_path: Path) -> None:
    path = write_capture(tmp_path / "c.cap", [b"aaaa"], tail=b"xx")
    with pytest.raises(CaptureError, match="partial frame"):
        list(CaptureReader(path))


def test_reader_paces_frames(tmp_path: Path) -> None:
    sleeps: list[float] = []
    path = write_capture(tmp_path / "c.cap", [b"aaaa", b"bbbb"])
    list(CaptureReader(path, fps=20, sleep=sleeps.append))
    assert sleeps == [0.05, 0.05]


def test_reader_loops_until_stopped(tmp_path: Path) -> None:
    path = write_capture(tmp_path / "c.cap", [b"aaaa", b"bbbb"])
    reader = CaptureReader(path, loop=True)
    got = []
    for frame in reader:
        got.append(frame)
        if len(got) == 5:
            reader.stop()
    assert got == [b"aaaa", b"bbbb", b"aaaa", b"bbbb", b"aaaa"]


def test_stop_from_another_thread(tmp_path: Path) -> None:
    path = write_capture(tmp_path / "c.cap", [b"aaaa"])
    reader = CaptureReader(path, loop=True, fps=1000)
    count = 0
    threading.Timer(0.05, reader.stop).start()
    for _ in reader:
        count += 1
    assert count > 1


def test_loop_on_empty_capture_errors(tmp_path: Path) -> None:
    path = write_capture(tmp_path / "c.cap", [])
    with pytest.raises(CaptureError, match="no frames"):
        list(CaptureReader(path, loop=True))
    assert list(CaptureReader(path)) == []


def test_negative_fps_rejected(tmp_path: Path) -> None:
    with pytest.raises(CaptureError, match="fps"):
        CaptureReader(write_capture(tmp_path / "c.cap", []), fps=-1)


def test_committed_fixture_is_valid() -> None:
    reader = CaptureReader(FIXTURE)
    frames = list(reader)
    assert reader.model == "FT-710"
    assert len(frames) == 8
    assert FIXTURE.stat().st_size < 64 * 1024
