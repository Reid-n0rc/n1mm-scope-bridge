# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Record and replay raw radio frames (docs/architecture.md, Capture file format).

A capture is one ASCII header line, ``N1MMSB1 <model> <frame-size>\\n``,
followed by whole raw frames. Replays let anyone test or debug the bridge,
or add a radio, without the radio itself.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO

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
