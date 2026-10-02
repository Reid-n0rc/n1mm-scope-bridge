# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Record and replay raw radio frames (docs/architecture.md, Capture file format).

A capture is one ASCII header line, ``N1MMSB1 <model> <frame-size>\\n``,
followed by whole raw frames. Replays let anyone test or debug the bridge,
or add a radio, without the radio itself. Raw stream captures
(``N1MMSB1-RAW``, below) keep every SPI read before alignment, for checking
the emulator against a real radio (#36).
"""

from __future__ import annotations

import re
import struct
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

MAGIC = "N1MMSB1"
_MODEL = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
MAX_FRAME_SIZE = 1 << 20


class CaptureError(ValueError):
    """The capture file is malformed."""


def format_header(model: str, frame_size: int) -> bytes:
    if not _MODEL.match(model):
        raise CaptureError(
            f"capture model name {model!r} must be 1-32 characters of A-Z, a-z, 0-9, . _ -"
        )
    if not 0 < frame_size <= MAX_FRAME_SIZE:
        raise CaptureError(f"frame size must be in 1..{MAX_FRAME_SIZE}, got {frame_size}")
    return f"{MAGIC} {model} {frame_size}\n".encode("ascii")


def parse_header(line: bytes) -> tuple[str, int]:
    try:
        magic, model, size_text = line.decode("ascii").rstrip("\n").split(" ")
        size = int(size_text)
    except (UnicodeDecodeError, ValueError):
        raise CaptureError("not an n1mm-scope-bridge capture (bad header)") from None
    if magic != MAGIC:
        raise CaptureError(f"unsupported capture format {magic!r}")
    format_header(model, size)  # validates the fields
    return model, size


class CaptureWriter:
    """Writes frames of one fixed size after a header."""

    def __init__(self, stream: BinaryIO, model: str, frame_size: int) -> None:
        stream.write(format_header(model, frame_size))
        self._stream = stream
        self.frame_size = frame_size
        self.frames = 0

    def write(self, frame: bytes) -> None:
        if len(frame) != self.frame_size:
            raise CaptureError(f"capture frame is {len(frame)} bytes, expected {self.frame_size}")
        self._stream.write(frame)
        self.frames += 1


class CaptureReader:
    """Iterates a capture's frames, optionally paced in real time and looped.

    ``stop()`` may be called from another thread to end the iteration.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        fps: float = 0.0,
        loop: bool = False,
        sleep: Callable[[float], object] = time.sleep,
    ) -> None:
        if fps < 0:
            raise CaptureError(f"replay fps must be >= 0, got {fps}")
        self.path = Path(path)
        with self.path.open("rb") as fh:
            self.model, self.frame_size = parse_header(fh.readline(64))
        self._fps = fps
        self._loop = loop
        self._sleep = sleep
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def __iter__(self) -> Iterator[bytes]:
        with self.path.open("rb") as fh:
            fh.readline(64)
            start = fh.tell()
            while True:
                count = 0
                while not self._stop.is_set():
                    frame = fh.read(self.frame_size)
                    if not frame:
                        break
                    if len(frame) != self.frame_size:
                        raise CaptureError(
                            f"{self.path.name}: trailing partial frame ({len(frame)} bytes)"
                        )
                    count += 1
                    yield frame
                    if self._fps:
                        self._sleep(1.0 / self._fps)
                if self._stop.is_set() or not self._loop:
                    return
                if count == 0:
                    raise CaptureError(f"{self.path.name}: capture has no frames to loop")
                fh.seek(start)


# --- Raw stream captures (issue #36) ---------------------------------------------------------
#
# A raw capture keeps exactly what each FT4222_SPIMaster_SingleRead returned, before
# alignment or resync, with a timestamp and status. That preserves start-up alignment,
# padding between frames, timing, and errors, which whole-frame captures lose. Layout:
#   b"N1MMSB1-RAW <model> <read-size>\n" then records of
#   struct "<dII" (seconds since start, FT status, length) followed by `length` bytes.

RAW_MAGIC = "N1MMSB1-RAW"
_RAW_RECORD = struct.Struct("<dII")
MAX_RAW_CHUNK = 1 << 16


@dataclass(frozen=True)
class RawChunk:
    t: float
    """Seconds since the capture started."""
    status: int
    data: bytes


def format_raw_header(model: str, read_size: int) -> bytes:
    format_header(model, read_size)  # validates the fields
    return f"{RAW_MAGIC} {model} {read_size}\n".encode("ascii")


def parse_raw_header(line: bytes) -> tuple[str, int]:
    text = line.decode("ascii", errors="replace")
    if not text.startswith(RAW_MAGIC + " "):
        raise CaptureError("not an n1mm-scope-bridge raw stream capture (bad header)")
    return parse_header((MAGIC + text[len(RAW_MAGIC) :]).encode("ascii"))


class RawStreamWriter:
    """Appends timestamped SPI read results after a header."""

    def __init__(
        self,
        stream: BinaryIO,
        model: str,
        read_size: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        stream.write(format_raw_header(model, read_size))
        self._stream = stream
        self._clock = clock
        self._start = clock()
        self.chunks = 0
        self.bytes = 0

    def write(self, status: int, data: bytes) -> None:
        if len(data) > MAX_RAW_CHUNK:
            raise CaptureError(f"raw chunk of {len(data)} bytes exceeds {MAX_RAW_CHUNK}")
        t = self._clock() - self._start
        self._stream.write(_RAW_RECORD.pack(t, status, len(data)) + data)
        self.chunks += 1
        self.bytes += len(data)


def read_raw_stream(path: str | Path) -> tuple[str, int, list[RawChunk]]:
    """Read a whole raw capture: (model, read size, chunks)."""
    path = Path(path)
    with path.open("rb") as fh:
        model, read_size = parse_raw_header(fh.readline(64))
        chunks: list[RawChunk] = []
        while True:
            head = fh.read(_RAW_RECORD.size)
            if not head:
                return model, read_size, chunks
            if len(head) != _RAW_RECORD.size:
                raise CaptureError(f"{path.name}: truncated raw record header")
            t, status, length = _RAW_RECORD.unpack(head)
            if length > MAX_RAW_CHUNK:
                raise CaptureError(f"{path.name}: raw chunk length {length} is too large")
            data = fh.read(length)
            if len(data) != length:
                raise CaptureError(f"{path.name}: truncated raw chunk")
            chunks.append(RawChunk(t, status, data))


class RecordingApi:
    """Wraps an ``Ft4222Api`` and records every SPI read to a ``RawStreamWriter``.

    Everything else passes straight through, so the normal reader (with its resync)
    drives the device exactly as in ``run``.
    """

    def __init__(self, inner: Any, writer: RawStreamWriter) -> None:
        self._inner = inner
        self._writer = writer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def spi_read(self, handle: Any, size: int) -> tuple[int, bytes]:
        status, data = self._inner.spi_read(handle, size)
        self._writer.write(status, data)
        return status, data


class RawStreamApi:
    """Serves a raw capture back as an ``Ft4222Api``, byte for byte.

    Read boundaries may differ from the recording (the reader asks for different
    sizes during resync), so the bytes are served as one continuous stream; a
    recorded error status is returned once all bytes before it were consumed.
    """

    def __init__(self, chunks: list[RawChunk]) -> None:
        self._chunks = list(chunks)
        self._buffer = bytearray()
        self._open = False
        self.calls: list[str] = []

    def open_ex(self, description: str) -> tuple[int, Any]:
        self.calls.append("open")
        self._open = True
        return 0, self

    def set_timeouts(self, handle: Any, read_ms: int, write_ms: int) -> int:
        return 0

    def set_latency_timer(self, handle: Any, ms: int) -> int:
        return 0

    def spi_master_init(self, handle: Any) -> int:
        return 0

    def set_clock(self, handle: Any) -> int:
        return 0

    def spi_read(self, handle: Any, size: int) -> tuple[int, bytes]:
        while len(self._buffer) < size and self._chunks:
            chunk = self._chunks[0]
            if chunk.status != 0:
                if self._buffer:
                    break
                self._chunks.pop(0)
                return chunk.status, b""
            self._buffer += chunk.data
            self._chunks.pop(0)
        data, self._buffer = bytes(self._buffer[:size]), self._buffer[size:]
        return 0, data

    def uninitialize(self, handle: Any) -> int:
        return 0

    def close(self, handle: Any) -> int:
        self.calls.append("close")
        self._open = False
        return 0
