# SPDX-License-Identifier: GPL-3.0-only
"""Radio-independent types that every supported radio plugs into.

A radio is a ``RadioProfile``: static facts about the model plus a pure
``parser`` that turns one raw transport frame into a ``ParsedFrame``. Transports
(``transport/``) only move bytes; parsing never does I/O. See
docs/adding-a-radio.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from n1mm_scope_bridge.spectrum import SpectrumFrame

ModeFamily = Literal["center", "cursor", "fixed", "unknown"]


class FrameError(ValueError):
    """A raw frame could not be parsed. The pipeline skips it and counts it."""


@dataclass(frozen=True)
class ScopeStatus:
    """What the radio's scope was showing when the frame was captured."""

    vfo_hz: int
    span_hz: int
    mode_family: ModeFamily
    mode_name: str

    @property
    def edges_verified(self) -> bool:
        """True when the frame's frequency edges are known to be exact."""
        return self.mode_family == "center"


@dataclass(frozen=True)
class ParsedFrame:
    spectrum: SpectrumFrame
    status: ScopeStatus


@dataclass(frozen=True)
class RadioProfile:
    key: str
    """CLI identifier, for example ``"ft710"``."""
    model: str
    """Display name and default N1MM source name, for example ``"FT-710"``."""
    transport: Literal["ft4222"]
    frame_size: int
    bins: int
    max_level: int
    spans_hz: tuple[int, ...]
    """Span in Hz, indexed by the radio's span code."""
    scope_modes: tuple[tuple[str, str], ...]
    """``(code, name)`` pairs for the radio's scope modes."""
    parser: Callable[[bytes, RadioProfile], ParsedFrame] = field(repr=False, compare=False)

    def parse(self, raw: bytes) -> ParsedFrame:
        return self.parser(raw, self)

    def scope_mode_name(self, code: str) -> str | None:
        return dict(self.scope_modes).get(code)
