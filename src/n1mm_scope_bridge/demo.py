# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Deterministic, realistic-looking FT-710 frames for demos, screenshots, and tests.

Builds raw FT4222 frames (noise floor plus a cluster of FT8-style signals and
a few CW carriers) without a radio.
"""

from __future__ import annotations

import random
import threading
from collections.abc import Iterator

from n1mm_scope_bridge.radios import yaesu_scope as ys


def encode_bcd(value: int, length: int = ys.BCD_LEN) -> bytes:
    """Packed BCD, most significant digit first (inverse of ``decode_bcd``)."""
    digits = f"{value:0{length * 2}d}"
    if value < 0 or len(digits) != length * 2:
        raise ValueError(f"{value} does not fit in {length} BCD bytes")
    return bytes(int(digits[i : i + 2], 16) for i in range(0, len(digits), 2))


def build_frame(
    shown_levels: bytes,
    *,
    vfo_a_hz: int,
    span_index: int,
    scope_mode: int = 0x04,
    vfo_b_hz: int = 7_074_000,
) -> bytes:
    """A raw FT4222 frame whose spectrum displays as ``shown_levels``."""
    if len(shown_levels) != ys.BINS:
        raise ValueError(f"need {ys.BINS} levels, got {len(shown_levels)}")
    buf = bytearray(ys.FRAME_SIZE)
    buf[ys.WF1 : ys.WF1 + ys.BINS] = bytes(255 - b for b in shown_levels)
    status = ys.DATA
    buf[status + ys.STATUS_SCOPE_MODE] = scope_mode
    buf[status + ys.STATUS_SPAN] = span_index
    buf[status + ys.STATUS_VFO_A : status + ys.STATUS_VFO_A + ys.BCD_LEN] = encode_bcd(vfo_a_hz)
    buf[status + ys.STATUS_VFO_B : status + ys.STATUS_VFO_B + ys.BCD_LEN] = encode_bcd(vfo_b_hz)
    buf[-len(ys.SYNC) :] = ys.SYNC
    return bytes(buf)


def demo_frames(
    count: int, *, vfo_a_hz: int = 14_074_000, span_index: int = 4, seed: int = 710
) -> list[bytes]:
    """``count`` frames of a busy 20 m FT8 segment (default span 20 kHz)."""
    if count < 1:
        raise ValueError("count must be >= 1")
    rng = random.Random(seed)
    span = (1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000, 500_000, 1_000_000)[
        span_index
    ]
    hz_per_bin = span / ys.BINS
    low = vfo_a_hz - span / 2
    signals = [(vfo_a_hz + rng.uniform(0, 3_000), rng.randint(40, 120)) for _ in range(14)]
    signals += [(vfo_a_hz - rng.uniform(2_000, 8_000), rng.randint(80, 150)) for _ in range(3)]
    frames = []
    for n in range(count):
        levels = [rng.randint(18, 34) for _ in range(ys.BINS)]
        for freq, strength in signals:
            center = int((freq - low) / hz_per_bin)
            width = max(1, int(50 / hz_per_bin))  # ~50 Hz wide
            on = (n + int(freq)) % 4 != 0  # signals key on and off
            for b in range(center - width, center + width + 1):
                if on and 0 <= b < ys.BINS:
                    levels[b] = min(255, max(levels[b], strength + rng.randint(-6, 6)))
        frames.append(build_frame(bytes(levels), vfo_a_hz=vfo_a_hz, span_index=span_index))
    return frames


class DemoStream:
    """Endless, paced stream of demo frames (self-tests, screenshots, demo mode).

    Iterate from one thread; ``stop()`` may be called from any thread.
    """

    def __init__(self, fps: float = 20.0, frames: int = 16, seed: int = 710) -> None:
        if fps <= 0:
            raise ValueError("fps must be greater than 0")
        self._frames = demo_frames(frames, seed=seed)
        self._period = 1.0 / fps
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def __iter__(self) -> Iterator[bytes]:
        while True:
            for frame in self._frames:
                if self._stop.wait(self._period):
                    return
                yield frame
