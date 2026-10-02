# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
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


class SpanUnavailable(FrameError):
    """A frame from a scope mode that doesn't report the span, with no earlier span to reuse."""


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
    parser: Callable[..., ParsedFrame] = field(repr=False, compare=False)
    """``parser(raw, profile, *, span_fallback_hz=None)``."""

    def parse(self, raw: bytes) -> ParsedFrame:
        return self.parser(raw, self)

    def scope_mode_name(self, code: str) -> str | None:
        return dict(self.scope_modes).get(code)


class FrameDecoder:
    """Stateful frame parser for one stream (one per pipeline).

    Some scope modes don't report the span (Cursor/Fixed on the FT-710, #111);
    the decoder remembers the last span seen and passes it to the parser.
    """

    def __init__(self, profile: RadioProfile) -> None:
        self.profile = profile
        self.last_span_hz: int | None = None

    def __call__(self, raw: bytes) -> ParsedFrame:
        parsed = self.profile.parser(raw, self.profile, span_fallback_hz=self.last_span_hz)
        if parsed.status.mode_family == "center":
            self.last_span_hz = parsed.status.span_hz
        return parsed
