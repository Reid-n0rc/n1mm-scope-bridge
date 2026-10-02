# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Compare the FT-710 emulator against golden captures from a real radio (issue #36).

Pure functions over raw stream captures (``transport.replay.read_raw_stream``).
``tests/test_emulator_conformance.py`` applies them to the committed golden
fixtures on every CI run; ``scripts/capture_golden.py`` records those fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from n1mm_scope_bridge.emulator.ft710 import Ft710Emulator, RadioState
from n1mm_scope_bridge.radios import yaesu_scope as ys
from n1mm_scope_bridge.radios.ft710 import FT710
from n1mm_scope_bridge.transport.ft4222 import Ft4222Error, Ft4222Reader
from n1mm_scope_bridge.transport.replay import RawChunk, RawStreamApi

Padding = Literal["sync", "zero", "other"]
FPS_TOLERANCE = 0.10
NOISE_FLOOR_TOLERANCE = 20  # levels (0-255): bands differ, so this is a sanity bound


@dataclass(frozen=True)
class Decoded:
    frames: list[bytes]
    resyncs: int


def decode_frames(chunks: list[RawChunk]) -> Decoded:
    """Whole frames the real reader gets from a raw capture, and the resyncs it needed."""
    reader = Ft4222Reader(RawStreamApi(chunks))
    frames: list[bytes] = []
    resyncs = 0
    try:
        for raw in reader:
            frames.append(raw)
            resyncs = reader.resyncs
    except Ft4222Error:
        pass  # end of capture
    return Decoded(frames, resyncs)


def padding_style(frame: bytes) -> Padding:
    """How the bytes between the status block and the sync tail are filled."""
    repeats = (ys.FRAME_SIZE - ys.DATA - ys.DATA_LEN) // len(ys.SYNC)
    tail = frame[ys.FRAME_SIZE - repeats * len(ys.SYNC) : -len(ys.SYNC)]
    if tail == ys.SYNC * (repeats - 1):
        return "sync"
    if not any(tail):
        return "zero"
    return "other"


def measured_fps(chunks: list[RawChunk], frame_size: int = ys.FRAME_SIZE) -> float | None:
    """Frames per second from the timestamps of whole-frame reads (None if too few)."""
    times = [c.t for c in chunks if c.status == 0 and len(c.data) == frame_size]
    if len(times) < 3 or times[-1] <= times[0]:
        return None
    return (len(times) - 1) / (times[-1] - times[0])


def noise_floor(levels: tuple[int, ...]) -> int:
    """10th-percentile level: a robust noise-floor estimate."""
    ordered = sorted(levels)
    return ordered[len(ordered) // 10]


def emulator_like(frame: bytes, *, padding: Padding = "sync") -> Ft710Emulator:
    """An emulator set to the radio state decoded from a real frame."""
    parsed = FT710.parse(frame)
    status = frame[ys.DATA : ys.DATA + ys.DATA_LEN]
    state = RadioState(
        vfo_a_hz=parsed.status.vfo_hz,
        span_index=FT710.spans_hz.index(parsed.status.span_hz),
        scope_mode=status[ys.STATUS_SCOPE_MODE],
        tx=status[22] & 0x80 != 0,
    )
    return Ft710Emulator(state, padding="zero" if padding == "zero" else "sync")


def compare(
    chunks: list[RawChunk], *, emulator_fps: float, emulator_padding: Padding = "sync"
) -> list[str]:
    """Differences between a real capture and the emulator (empty when they agree)."""
    decoded = decode_frames(chunks)
    if not decoded.frames:
        return ["no whole frames in the capture"]
    problems: list[str] = []
    real = decoded.frames[-1]
    style = padding_style(real)
    if style != emulator_padding:
        problems.append(f"real frames use {style!r} padding, emulator uses {emulator_padding!r}")
    emu = emulator_like(real, padding=style)
    reader = Ft4222Reader(emu)
    reader.open()
    emu_frame = reader.read_frame()
    reader.close()
    assert emu_frame is not None
    r, e = FT710.parse(real).status, FT710.parse(emu_frame).status
    for field in ("vfo_hz", "span_hz", "mode_family", "mode_name"):
        if getattr(r, field) != getattr(e, field):
            problems.append(f"{field}: radio {getattr(r, field)!r}, emulator {getattr(e, field)!r}")
    fps = measured_fps(chunks)
    if fps is not None and abs(fps - emulator_fps) > emulator_fps * FPS_TOLERANCE:
        problems.append(f"frame rate: radio {fps:.1f}/s, emulator {emulator_fps:.1f}/s")
    real_floor = noise_floor(FT710.parse(real).spectrum.levels)
    emu_floor = noise_floor(FT710.parse(emu_frame).spectrum.levels)
    if abs(real_floor - emu_floor) > NOISE_FLOOR_TOLERANCE:
        problems.append(f"noise floor: radio {real_floor}, emulator {emu_floor}")
    return problems
