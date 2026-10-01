# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Wire a radio source into N1MM+: parse -> combine -> encode -> send.

``build_pipeline`` returns a threaded ``Pipeline`` (docs/architecture.md,
Concurrency) whose process stage parses raw frames with the radio profile and
whose sender stage encodes the combined spectrum as N1MM's ``<Spectrum>``
packet.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, get_args

from n1mm_scope_bridge.n1mm import DEFAULT_APP, encode_spectrum
from n1mm_scope_bridge.pipeline import Pipeline
from n1mm_scope_bridge.radios.base import ParsedFrame, RadioProfile, ScopeStatus
from n1mm_scope_bridge.spectrum import SpectrumFrame

Combine = Literal["latest", "average", "peak"]
COMBINE_MODES: tuple[str, ...] = get_args(Combine)
DEFAULT_SCALING = 0.3125  # UNVERIFIED (#5): ~80 dB over 256 steps
DEFAULT_RATE_HZ = 4.0


class SpectrumCombiner:
    """Thread-safe ``Accumulator[ParsedFrame]`` for the latest/average/peak modes.

    Frames are combined only while the frequency edges and bin count stay the
    same. A retune or span change starts over with the new frame.
    """

    def __init__(self, mode: Combine = "latest") -> None:
        if mode not in COMBINE_MODES:
            raise ValueError(f"combine must be one of {', '.join(COMBINE_MODES)}, got {mode!r}")
        self.mode = mode
        self._lock = threading.Lock()
        self._last: ParsedFrame | None = None
        self._acc: list[int] = []
        self._count = 0

    def add(self, item: ParsedFrame) -> None:
        spec = item.spectrum
        with self._lock:
            last = self._last
            same = (
                last is not None
                and self.mode != "latest"
                and (last.spectrum.low_hz, last.spectrum.high_hz, len(last.spectrum.levels))
                == (spec.low_hz, spec.high_hz, len(spec.levels))
            )
            if not same:
                self._acc = list(spec.levels)
                self._count = 1
            elif self.mode == "average":
                self._acc = [a + b for a, b in zip(self._acc, spec.levels, strict=True)]
                self._count += 1
            else:
                self._acc = [max(a, b) for a, b in zip(self._acc, spec.levels, strict=True)]
                self._count = 1
            self._last = item

    def take(self) -> ParsedFrame | None:
        with self._lock:
            last, count, acc = self._last, self._count, self._acc
            self._last, self._acc, self._count = None, [], 0
        if last is None:
            return None
        levels = tuple(round(v / count) for v in acc) if count > 1 else tuple(acc)
        spec = last.spectrum
        combined = SpectrumFrame(spec.low_hz, spec.high_hz, levels, spec.max_level)
        return ParsedFrame(spectrum=combined, status=last.status)


class RateLimiter:
    """Allows one event per ``interval`` seconds (for log lines in the frame loop)."""

    def __init__(self, interval: float = 1.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._interval = interval
        self._clock = clock
        self._next = float("-inf")
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = self._clock()
            if now < self._next:
                return False
            self._next = now + self._interval
            return True


class PacketSender(Protocol):
    def send(self, payload: bytes) -> bool:
        """Send one datagram; False if it could not be sent."""


@dataclass(frozen=True)
class BridgeConfig:
    profile: RadioProfile
    name: str
    """Source name shown in N1MM+'s Spectrum Display settings."""
    scaling: float = DEFAULT_SCALING
    rate_hz: float = DEFAULT_RATE_HZ
    combine: Combine = "latest"
    app: str = DEFAULT_APP

    def __post_init__(self) -> None:
        if self.combine not in COMBINE_MODES:
            raise ValueError(f"combine must be one of {', '.join(COMBINE_MODES)}")
        if not 0 < self.rate_hz <= 10:
            raise ValueError(f"rate must be in (0, 10] updates per second, got {self.rate_hz}")
        # Validates name, app, and scaling exactly as each packet will.
        probe = SpectrumFrame(0, 1, (0,), self.profile.max_level)
        encode_spectrum(probe, name=self.name, scaling=self.scaling, app=self.app)


CENTER_MODE_WARNING = (
    "{model} scope is in {mode} mode; frequency edges are only exact in Center mode. "
    "Set the radio's scope to Center for an accurate N1MM display."
)


def build_pipeline(
    config: BridgeConfig,
    source: Iterable[bytes],
    sender: PacketSender,
    *,
    close_source: Callable[[], object] | None = None,
    on_status: Callable[[ScopeStatus], object] | None = None,
    warn: Callable[[str], object] = print,
    clock: Callable[[], float] = time.monotonic,
) -> Pipeline[ParsedFrame]:
    """Build (but do not start) the reader -> process -> sender pipeline."""
    limiter = RateLimiter(1.0, clock)

    def emit(item: ParsedFrame) -> None:
        payload = encode_spectrum(
            item.spectrum, name=config.name, scaling=config.scaling, app=config.app
        )
        sender.send(payload)
        if not item.status.edges_verified and limiter.allow():
            warn(CENTER_MODE_WARNING.format(model=config.profile.model, mode=item.status.mode_name))
        if on_status is not None:
            on_status(item.status)

    return Pipeline(
        config.profile.key,
        source,
        config.profile.parse,
        emit,
        rate_hz=config.rate_hz,
        accumulator=SpectrumCombiner(config.combine),
        close_source=close_source,
        clock=clock,
    )
