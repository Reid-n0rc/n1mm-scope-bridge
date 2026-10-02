# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Software FT-710 behind the ``Ft4222Api`` interface (issue #35).

Everything above the FTDI boundary (reader, resync, parser, pipeline, CLI,
GUI) runs unmodified against it, so tests, CI, demos, and screenshots need no
radio. Behaviour is validated against golden captures from a real FT-710
(#36). Until then, start-up alignment and inter-frame bytes are
UNVERIFIED (#36).
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from n1mm_scope_bridge.demo import build_frame
from n1mm_scope_bridge.radios import yaesu_scope as ys
from n1mm_scope_bridge.radios.ft710 import FT710
from n1mm_scope_bridge.transport.ft4222 import DEFAULT_DESCRIPTION, FT_OK

FT_DEVICE_NOT_FOUND = 2
FT_DEVICE_NOT_OPENED = 3
FT_IO_ERROR = 4
TX_STATUS = (0x80, 0x28)  # status bytes 22-23 while transmitting (wfview notes)
RX_STATUS = (0x00, 0x08)
SETUP_STEPS = ("timeouts", "latency", "spi_init", "clock")


# 10th-percentile level per span index, measured on a real FT-710 on 40 m
# (7.074 MHz, evening, issue #111). Wider spans fold more bandwidth into each bin.
NOISE_FLOOR_BY_SPAN: tuple[int, ...] = (37, 44, 47, 52, 57, 70, 77, 83, 88, 90)


@dataclass
class RadioState:
    """What the operator has set on the radio. Change it through the emulator's methods."""

    vfo_a_hz: int = 14_074_000
    vfo_b_hz: int = 7_074_000
    span_index: int = 4
    scope_mode: int = 0x04  # Center (Normal)
    tx: bool = False
    s_meter: int = 40


@dataclass(frozen=True)
class Signal:
    freq_hz: int
    level: int
    width_hz: int = 50
    duty: float = 0.75
    """Fraction of frames the signal is keyed (FT8 and CW come and go)."""


DEFAULT_SIGNALS: tuple[Signal, ...] = (
    *(Signal(14_074_300 + i * 190, 60 + (i * 37) % 70) for i in range(14)),  # FT8 cluster
    Signal(14_025_400, 120, 30, 0.6),
    Signal(14_031_800, 95, 30, 0.6),
    Signal(14_038_100, 140, 30, 0.5),  # CW
    Signal(14_205_000, 110, 2_400, 0.9),
    Signal(14_250_000, 80, 2_400, 0.8),  # SSB
)


@dataclass
class Faults:
    """Failure modes a test or scenario can switch on."""

    open_status: int = FT_OK
    """Status FT_OpenEx returns (for example FT_DEVICE_NOT_FOUND)."""
    setup_failure: str | None = None
    """One of SETUP_STEPS to fail with FT_IO_ERROR."""
    start_offset: int = 0
    """Junk bytes before the first frame (a misaligned stream)."""
    corrupt_every: int = 0
    """Break the sync tail of every Nth frame (forces a resync)."""
    silent: bool = False
    """The device opens but never produces data."""
    io_error_after_frames: int | None = None
    """Reads fail with FT_IO_ERROR after this many frames (USB unplugged)."""


FrameHook = Callable[["Ft710Emulator", int], None]


@dataclass
class _Handle:
    serial: int


class Ft710Emulator:
    """An FT-710 scope stream behind ``Ft4222Api`` (thread-safe)."""

    def __init__(  # noqa: PLR0913 - keyword-only options plus injected sleep/clock
        self,
        state: RadioState | None = None,
        *,
        signals: tuple[Signal, ...] = DEFAULT_SIGNALS,
        faults: Faults | None = None,
        fps: float = 0.0,
        seed: int = 710,
        on_frame: FrameHook | None = None,
        padding: Literal["tail", "sync", "zero"] = "tail",
        sleep: Callable[[float], object] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.state = state or RadioState()
        self.signals = signals
        self.faults = faults or Faults()
        self.on_frame = on_frame
        # Bytes between the status block and the sync tail. A real FT-710 (#111)
        # sends zeros and ends each frame with the sync pattern four times ("tail");
        # "sync" and "zero" remain for resync tests.
        self.padding = padding
        self._period = 1.0 / fps if fps > 0 else 0.0
        self._sleep = sleep
        self._clock = clock
        self._next_due: float | None = None
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._open: _Handle | None = None
        self._opens = 0
        self.frames_generated = 0
        self.calls: list[str] = []

    # -- operator controls (any thread) -------------------------------------------

    def tune(self, vfo_a_hz: int) -> None:
        with self._lock:
            self.state.vfo_a_hz = vfo_a_hz

    def set_span(self, index: int) -> None:
        if not 0 <= index < len(FT710.spans_hz):
            raise ValueError(f"span index must be 0..{len(FT710.spans_hz) - 1}")
        with self._lock:
            self.state.span_index = index

    def set_scope_mode(self, byte: int) -> None:
        with self._lock:
            self.state.scope_mode = byte

    def set_tx(self, on: bool) -> None:
        with self._lock:
            self.state.tx = on

    # -- spectrum ----------------------------------------------------------------

    def render_levels(self, frame_index: int) -> bytes:
        """The displayed (not inverted) 850-bin spectrum for the current state."""
        st = self.state
        span = FT710.spans_hz[st.span_index]
        low = st.vfo_a_hz - span // 2
        hz_per_bin = span / ys.BINS
        floor = NOISE_FLOOR_BY_SPAN[st.span_index]
        # Uniform noise whose 10th percentile matches the measured floor (#111).
        levels = [self._rng.randint(floor - 4, floor + 36) for _ in range(ys.BINS)]
        lift = floor - NOISE_FLOOR_BY_SPAN[0]  # keep signals above the floor at wide spans
        signals = list(self.signals)
        if st.tx:
            signals.append(Signal(st.vfo_a_hz, 230, 2_400, 1.0))
        for sig in signals:
            keyed = (hash((sig.freq_hz, frame_index)) % 1000) / 1000 < sig.duty
            if not keyed:
                continue
            first = int((sig.freq_hz - sig.width_hz / 2 - low) / hz_per_bin)
            last = int((sig.freq_hz + sig.width_hz / 2 - low) / hz_per_bin)
            for b in range(max(first, 0), min(max(last, first) + 1, ys.BINS)):
                level = sig.level + lift + self._rng.randint(-6, 6)
                levels[b] = min(255, max(levels[b], level))
        return bytes(levels)

    def _next_frame(self) -> bytes:
        index = self.frames_generated
        if self.on_frame is not None:
            self.on_frame(self, index)
        with self._lock:
            st = self.state
            frame = bytearray(
                build_frame(
                    self.render_levels(index),
                    vfo_a_hz=st.vfo_a_hz,
                    span_index=st.span_index,
                    scope_mode=st.scope_mode,
                    vfo_b_hz=st.vfo_b_hz,
                )
            )
            frame[ys.DATA + 22 : ys.DATA + 24] = bytes(TX_STATUS if st.tx else RX_STATUS)
            frame[ys.DATA + ys.STATUS_S_METER] = st.s_meter
            family = ys.mode_family(FT710.scope_mode_name(ys.scope_mode_code(st.scope_mode)))
            flags = {"cursor": 0x40, "fixed": 0x80}.get(family, 0x00)
            frame[ys.DATA + ys.STATUS_SPAN] = st.span_index | flags
            frame[ys.DATA + ys.STATUS_MODE_FAMILY] = {"cursor": 1, "fixed": 2}.get(family, 0)
            vfo = st.vfo_a_hz.to_bytes(4, "big")
            start = (st.vfo_a_hz // 100_000 * 100_000) if family == "fixed" else st.vfo_a_hz
            frame[ys.DATA + ys.STATUS_VFO_A_BIN : ys.DATA + ys.STATUS_VFO_A_BIN + 4] = vfo
            frame[ys.DATA + ys.STATUS_SCOPE_START : ys.DATA + ys.STATUS_SCOPE_START + 4] = (
                start.to_bytes(4, "big")
            )
            if self.padding == "sync":
                repeats = (ys.FRAME_SIZE - ys.DATA - ys.DATA_LEN) // len(ys.SYNC)
                frame[ys.FRAME_SIZE - repeats * len(ys.SYNC) :] = ys.SYNC * repeats
            elif self.padding == "tail":  # verified on a real FT-710 (#111)
                frame[ys.FRAME_SIZE - 4 * len(ys.SYNC) :] = ys.SYNC * 4
        corrupt = self.faults.corrupt_every
        if corrupt and (index + 1) % corrupt == 0:
            frame[-1] ^= 0xFF
        if len(frame) != ys.FRAME_SIZE:  # pragma: no cover - internal invariant
            raise AssertionError(f"emulator built a {len(frame)}-byte frame")
        self.frames_generated += 1
        if self._period:
            # Deadline-based pacing: generation time counts toward the period, so
            # the emulator streams at exactly `fps` (checked against the radio, #36).
            now = self._clock()
            due = now + self._period if self._next_due is None else self._next_due + self._period
            due = max(due, now)  # fell behind (slow machine): don't catch up in a burst
            self._next_due = due
            self._sleep(max(0.0, due - now))
        return bytes(frame)

    # -- Ft4222Api ---------------------------------------------------------------

    def open_ex(self, description: str) -> tuple[int, Any]:
        self.calls.append("open")
        if description != DEFAULT_DESCRIPTION:
            return FT_DEVICE_NOT_FOUND, None
        if self.faults.open_status != FT_OK:
            return self.faults.open_status, None
        if self._open is not None:
            return FT_DEVICE_NOT_OPENED, None  # already open elsewhere (wfview running?)
        self._opens += 1
        self._open = _Handle(self._opens)
        self._buffer = bytearray(
            bytes(self._rng.randrange(256) for _ in range(self.faults.start_offset))
        )
        return FT_OK, self._open

    def _setup(self, step: str) -> int:
        self.calls.append(step)
        return FT_IO_ERROR if self.faults.setup_failure == step else FT_OK

    def set_timeouts(self, handle: Any, read_ms: int, write_ms: int) -> int:
        return self._setup("timeouts")

    def set_latency_timer(self, handle: Any, ms: int) -> int:
        return self._setup("latency")

    def spi_master_init(self, handle: Any) -> int:
        return self._setup("spi_init")

    def set_clock(self, handle: Any) -> int:
        return self._setup("clock")

    def spi_read(self, handle: Any, size: int) -> tuple[int, bytes]:
        if handle is None or handle is not self._open:
            return 1, b""  # FT_INVALID_HANDLE
        limit = self.faults.io_error_after_frames
        if limit is not None and self.frames_generated >= limit and not self._buffer:
            return FT_IO_ERROR, b""
        if self.faults.silent:
            return FT_OK, b""
        while len(self._buffer) < size:
            if limit is not None and self.frames_generated >= limit:
                break
            self._buffer += self._next_frame()
        data, self._buffer = bytes(self._buffer[:size]), self._buffer[size:]
        return FT_OK, data

    def uninitialize(self, handle: Any) -> int:
        self.calls.append("uninit")
        return FT_OK

    def close(self, handle: Any) -> int:
        self.calls.append("close")
        if handle is self._open:
            self._open = None
        return FT_OK
