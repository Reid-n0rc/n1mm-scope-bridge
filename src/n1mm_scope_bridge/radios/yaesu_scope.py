# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
# SPDX-FileCopyrightText: 2017-2026 Elliott H. Liggett (W6EL) and Phil Taylor (M0VSE)
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see <https://www.gnu.org/licenses/>.
#
# Portions derived from wfview (https://gitlab.com/eliggett/wfview):
#   wfview is copyright 2017-2026 Elliott H. Liggett (W6EL) and Phil Taylor
#   (M0VSE). All rights reserved. wfview source code is licensed via the GNU
#   GPLv3.
#   src/radio/yaesucommander.cpp:
#   Copyright 2017-2024 Elliott H. Liggett W6EL and Phil E. Taylor M0VSE
#
# Modified by Reid Crowe, N0RC, 2026-10-01: ported from C++/Qt to Python.
#   Frame layout from include/packettypes.h (yaesu_scope_data) and the sync
#   pattern from src/ft4222handler.cpp, re-expressed as offset constants.
#   Status decoding from yaesuCommander::haveScopeData() rewritten as a pure
#   function: adds validation (length, sync, BCD, span index, negative edge),
#   raises FrameError instead of continuing, and does not update radio state.
"""Parser for Yaesu scope frames read through the radio's FT4222 SPI bridge.

Derived from wfview; see the header above and THIRD_PARTY.md.
Frame layout and open questions: docs/protocol-yaesu-ft4222.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from n1mm_scope_bridge.radios.base import (
    FrameError,
    ModeFamily,
    ParsedFrame,
    RadioProfile,
    ScopeStatus,
)
from n1mm_scope_bridge.spectrum import SpectrumFrame

FRAME_SIZE = 4096
SYNC = b"\xff\x01\xee\x01"
BINS = 850

# Offsets into the frame (yaesu_scope_data union).
WF1 = 0
WF2 = 850
DATA = 2900
DATA_LEN = 150

# Offsets into the 150-byte status block (haveScopeData comment table).
STATUS_SCOPE_MODE = 17
STATUS_SPAN = 32
STATUS_MODE_FAMILY = 52  # UNVERIFIED (#5): 00 center, 01 cursor, 02 fixed
STATUS_VFO_A = 64
STATUS_VFO_B = 89
STATUS_S_METER = 110
BCD_LEN = 5

# wfview inverts every spectrum byte (`~b`) so that larger means stronger.
_INVERT = bytes(range(255, -1, -1))


@dataclass(frozen=True)
class YaesuScopeStatus(ScopeStatus):
    vfo_b_hz: int
    s_meter: int
    scope_mode_code: str
    raw_mode_family: int
    """Status byte 52, kept so hardware validation (#5) can compare it."""


def is_valid_frame(raw: bytes) -> bool:
    """True if ``raw`` is a whole frame that ends with the sync pattern."""
    return len(raw) == FRAME_SIZE and raw.endswith(SYNC)


def decode_bcd(data: bytes) -> int:
    """Decode packed BCD, most significant digit first (``00 14 07 40 00`` -> 14074000)."""
    value = 0
    for byte in data:
        hi, lo = byte >> 4, byte & 0x0F
        if hi > 9 or lo > 9:
            raise FrameError(f"invalid BCD byte 0x{byte:02X}")
        value = value * 100 + hi * 10 + lo
    return value


def scope_mode_code(byte: int) -> str:
    """wfview's mode code: the first hex digit of status byte 17 (0x05 -> "5", 0x40 -> "4")."""
    return f"{byte:X}"[0]


def mode_family(name: str | None) -> ModeFamily:
    if name is None:
        return "unknown"
    lowered = name.lower()
    for family in ("center", "cursor", "fixed"):
        if family in lowered:
            return family
    return "unknown"


def parse_frame(raw: bytes, profile: RadioProfile) -> ParsedFrame:
    """Parse one FT4222 scope frame into a spectrum line and scope status.

    Edges are VFO-A +/- span/2, as in wfview. That is exact in Center mode
    only; other modes are reported through ``status.edges_verified``.
    UNVERIFIED (#5): Cursor and Fixed mode edges.
    """
    if len(raw) != profile.frame_size:
        raise FrameError(f"frame is {len(raw)} bytes, expected {profile.frame_size}")
    if not raw.endswith(SYNC):
        raise FrameError("frame does not end with the FT4222 sync pattern")

    status = raw[DATA : DATA + DATA_LEN]
    span_index = status[STATUS_SPAN]
    if span_index >= len(profile.spans_hz):
        raise FrameError(f"span index {span_index} is outside 0..{len(profile.spans_hz) - 1}")
    span_hz = profile.spans_hz[span_index]
    vfo_a = decode_bcd(status[STATUS_VFO_A : STATUS_VFO_A + BCD_LEN])
    vfo_b = decode_bcd(status[STATUS_VFO_B : STATUS_VFO_B + BCD_LEN])

    half = span_hz // 2
    low, high = vfo_a - half, vfo_a + (span_hz - half)
    if low < 0:
        raise FrameError(f"VFO-A {vfo_a} Hz minus half the {span_hz} Hz span is below 0 Hz")

    code = scope_mode_code(status[STATUS_SCOPE_MODE])
    name = profile.scope_mode_name(code)
    levels = tuple(raw[WF1 : WF1 + profile.bins].translate(_INVERT))

    return ParsedFrame(
        spectrum=SpectrumFrame(
            low_hz=low, high_hz=high, levels=levels, max_level=profile.max_level
        ),
        status=YaesuScopeStatus(
            vfo_hz=vfo_a,
            span_hz=span_hz,
            mode_family=mode_family(name),
            mode_name=name or f"unknown ({code})",
            vfo_b_hz=vfo_b,
            s_meter=status[STATUS_S_METER],
            scope_mode_code=code,
            raw_mode_family=status[STATUS_MODE_FAMILY],
        ),
    )
