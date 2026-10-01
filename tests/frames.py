# SPDX-License-Identifier: GPL-3.0-only
"""Builders for synthetic radio frames used across the test suite."""

from __future__ import annotations

from n1mm_scope_bridge.radios import yaesu_scope as ys


def bcd(value: int, length: int = ys.BCD_LEN) -> bytes:
    digits = f"{value:0{length * 2}d}"
    if len(digits) != length * 2:
        raise ValueError("value too large for BCD field")
    return bytes(int(digits[i : i + 2], 16) for i in range(0, len(digits), 2))


def make_ft4222_frame(
    *,
    vfo_a_hz: int = 14_074_000,
    vfo_b_hz: int = 7_074_000,
    span_index: int = 6,
    scope_mode: int = 0x04,
    mode_family: int = 0x00,
    s_meter: int = 42,
    levels: bytes | None = None,
    sync: bytes = ys.SYNC,
) -> bytes:
    """A 4096-byte FT-710 frame. ``levels`` are the *displayed* (already inverted) values."""
    buf = bytearray(ys.FRAME_SIZE)
    shown = levels if levels is not None else bytes(i % 256 for i in range(ys.BINS))
    buf[ys.WF1 : ys.WF1 + len(shown)] = bytes(255 - b for b in shown)
    status = ys.DATA
    buf[status + ys.STATUS_SCOPE_MODE] = scope_mode
    buf[status + ys.STATUS_SPAN] = span_index
    buf[status + ys.STATUS_MODE_FAMILY] = mode_family
    buf[status + ys.STATUS_VFO_A : status + ys.STATUS_VFO_A + ys.BCD_LEN] = bcd(vfo_a_hz)
    buf[status + ys.STATUS_VFO_B : status + ys.STATUS_VFO_B + ys.BCD_LEN] = bcd(vfo_b_hz)
    buf[status + ys.STATUS_S_METER] = s_meter
    buf[ys.FRAME_SIZE - len(sync) :] = sync
    return bytes(buf)
