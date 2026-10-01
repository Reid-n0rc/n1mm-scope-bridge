# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Radio-independent spectrum line passed between the pipeline stages.

Frames are immutable (frozen dataclass, tuple of ints) so they can be handed
between threads without locks (see docs/architecture.md).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Largest level N1MM+ accepts in ``SpectrumData`` (docs/n1mm-spectrum-protocol.md).
MAX_N1MM_LEVEL = 65535


@dataclass(frozen=True)
class SpectrumFrame:
    """One spectrum line.

    ``levels[0]`` is the signal level at ``low_hz`` and ``levels[-1]`` at
    ``high_hz``. ``max_level`` is the largest value the source can produce
    (255 for the FT-710), which consumers use for scaling.
    """

    low_hz: int
    high_hz: int
    levels: tuple[int, ...]
    max_level: int

    def __post_init__(self) -> None:
        if not isinstance(self.levels, tuple):
            raise TypeError("levels must be a tuple of ints")
        if self.low_hz < 0:
            raise ValueError(f"low_hz must be >= 0, got {self.low_hz}")
        if self.high_hz <= self.low_hz:
            raise ValueError(
                f"high_hz ({self.high_hz}) must be greater than low_hz ({self.low_hz})"
            )
        if not 0 < self.max_level <= MAX_N1MM_LEVEL:
            raise ValueError(f"max_level must be in 1..{MAX_N1MM_LEVEL}, got {self.max_level}")
        if not self.levels:
            raise ValueError("levels must not be empty")
        for i, level in enumerate(self.levels):
            if not 0 <= level <= self.max_level:
                raise ValueError(f"levels[{i}] = {level} is outside 0..{self.max_level}")

    @property
    def span_hz(self) -> int:
        return self.high_hz - self.low_hz
