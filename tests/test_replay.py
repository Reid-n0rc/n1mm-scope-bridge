# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import io
import struct
import threading
from pathlib import Path

import pytest
from fakes import FakeApi

from n1mm_scope_bridge.transport.replay import (
    MAX_RAW_CHUNK,
    CaptureError,
    CaptureReader,
    CaptureWriter,
    RawChunk,
    RawStreamApi,
    RawStreamWriter,
    RecordingApi,
    format_header,
    parse_header,
    read_raw_stream,
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


# --- raw stream captures (#36) -----------------------------------------------------------


def test_raw_stream_round_trip(tmp_path: Path) -> None:
    ticks = iter([0.0, 0.5, 1.25])
    buf = io.BytesIO()
    writer = RawStreamWriter(buf, "FT-710", 4096, clock=lambda: next(ticks))
    writer.write(0, b"abc")
    writer.write(4, b"")
    assert (writer.chunks, writer.bytes) == (2, 3)
    path = tmp_path / "r.raw"
    path.write_bytes(buf.getvalue())
    model, size, chunks = read_raw_stream(path)
    assert (model, size) == ("FT-710", 4096)
    assert chunks == [RawChunk(0.5, 0, b"abc"), RawChunk(1.25, 4, b"")]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"N1MMSB1 FT-710 4096\n", "not an n1mm-scope-bridge raw stream capture"),
        (b"N1MMSB1-RAW FT-710 4096\n\x00\x01", "truncated raw record header"),
        (
            b"N1MMSB1-RAW FT-710 4096\n" + struct.pack("<dII", 0.0, 0, 10) + b"abc",
            "truncated raw chunk",
        ),
        (
            b"N1MMSB1-RAW FT-710 4096\n" + struct.pack("<dII", 0.0, 0, 1 << 20),
            "too large",
        ),
    ],
)
def test_raw_stream_errors(tmp_path: Path, content: bytes, message: str) -> None:
    path = tmp_path / "bad.raw"
    path.write_bytes(content)
    with pytest.raises(CaptureError, match=message):
        read_raw_stream(path)


def test_raw_writer_rejects_oversized_chunk() -> None:
    writer = RawStreamWriter(io.BytesIO(), "FT-710", 4096)
    with pytest.raises(CaptureError, match="raw chunk of"):
        writer.write(0, b"\x00" * (MAX_RAW_CHUNK + 1))


def test_recording_api_records_reads_and_passes_through() -> None:
    buf = io.BytesIO()
    inner = FakeApi(b"hello world")
    api = RecordingApi(inner, RawStreamWriter(buf, "FT-710", 4096))
    status, handle = api.open_ex("FT4222 A")  # passed through
    assert status == 0
    assert api.spi_read(handle, 5) == (0, b"hello")
    assert buf.getvalue().endswith(b"hello")


def test_raw_stream_api_serves_bytes_across_chunk_boundaries() -> None:
    api = RawStreamApi([RawChunk(0, 0, b"abc"), RawChunk(1, 0, b"defg"), RawChunk(2, 4, b"")])
    status, handle = api.open_ex("FT4222 A")
    assert status == 0
    assert all(f(handle) == 0 for f in (api.spi_master_init, api.set_clock, api.uninitialize))
    assert api.set_timeouts(handle, 1, 1) == 0
    assert api.set_latency_timer(handle, 2) == 0
    assert api.spi_read(handle, 5) == (0, b"abcde")
    assert api.spi_read(handle, 5) == (0, b"fg")  # bytes before the error come first
    assert api.spi_read(handle, 5) == (4, b"")  # then the recorded error
    assert api.spi_read(handle, 5) == (0, b"")  # then end of capture
    assert api.close(handle) == 0
    assert api.calls == ["open", "close"]
