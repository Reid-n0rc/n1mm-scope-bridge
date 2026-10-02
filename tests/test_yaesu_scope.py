# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import pytest
from frames import bcd, make_ft4222_frame

from n1mm_scope_bridge.radios import yaesu_scope as ys
from n1mm_scope_bridge.radios.base import FrameDecoder, FrameError, SpanUnavailable
from n1mm_scope_bridge.radios.ft710 import FT710


def test_layout_constants_match_wfview_union() -> None:
    # wf1, wf2, audio1fft, audio1scope, audio2fft, audio2scope, data, unused, sync
    sizes = [850, 850, 200, 400, 200, 400, 150, 1042, 4]
    assert sum(sizes) == ys.FRAME_SIZE
    assert sum(sizes[:6]) == ys.DATA
    assert ys.WF2 == 850


def test_parse_center_mode_frame() -> None:
    parsed = ys.parse_frame(make_ft4222_frame(), FT710)
    spec, status = parsed.spectrum, parsed.status
    assert (spec.low_hz, spec.high_hz) == (14_024_000, 14_124_000)
    assert len(spec.levels) == 850
    assert spec.levels[:3] == (0, 1, 2)
    assert spec.levels[255] == 255
    assert spec.max_level == 255
    assert status.vfo_hz == 14_074_000
    assert status.span_hz == 100_000
    assert status.mode_family == "center"
    assert status.mode_name == "Center (Normal)"
    assert status.edges_verified is True
    assert isinstance(status, ys.YaesuScopeStatus)
    assert status.vfo_b_hz == 7_074_000
    assert status.s_meter == 42
    assert status.scope_mode_code == "4"
    assert status.raw_mode_family == 0


def test_profile_parse_delegates() -> None:
    frame = make_ft4222_frame()
    assert FT710.parse(frame) == ys.parse_frame(frame, FT710)


def test_levels_are_inverted() -> None:
    shown = bytes([0, 255, 128] + [7] * 847)
    parsed = ys.parse_frame(make_ft4222_frame(levels=shown), FT710)
    assert parsed.spectrum.levels == tuple(shown)


@pytest.mark.parametrize(("index", "span"), list(enumerate(FT710.spans_hz)))
def test_every_span(index: int, span: int) -> None:
    parsed = ys.parse_frame(make_ft4222_frame(span_index=index), FT710)
    assert parsed.spectrum.span_hz == span
    assert parsed.spectrum.low_hz == 14_074_000 - span // 2


def test_odd_span_keeps_full_width() -> None:
    profile = FT710.__class__(**{**FT710.__dict__, "spans_hz": (1_001,)})
    parsed = ys.parse_frame(make_ft4222_frame(span_index=0), profile)
    assert parsed.spectrum.span_hz == 1_001


@pytest.mark.parametrize(
    ("byte", "code", "family"),
    [
        (0x00, "0", "center"),
        (0x01, "1", "cursor"),
        (0x02, "2", "fixed"),
        (0x05, "5", "center"),
        (0x07, "7", "cursor"),
        (0x0A, "A", "fixed"),
        (0x40, "4", "center"),
        (0x9F, "9", "fixed"),
    ],
)
def test_scope_mode_decoding(byte: int, code: str, family: str) -> None:
    status = ys.parse_frame(make_ft4222_frame(scope_mode=byte), FT710).status
    assert status.mode_family == family
    assert status.edges_verified is (family == "center")
    assert isinstance(status, ys.YaesuScopeStatus)
    assert status.scope_mode_code == code


def test_unknown_scope_mode() -> None:
    status = ys.parse_frame(make_ft4222_frame(scope_mode=0x0F), FT710).status
    assert status.mode_family == "unknown"
    assert status.mode_name == "unknown (F)"
    assert status.edges_verified is False


def test_mode_family_without_keyword() -> None:
    assert ys.mode_family("Waterfall only") == "unknown"
    assert ys.mode_family(None) == "unknown"


@pytest.mark.parametrize(
    ("data", "value"),
    [
        (bytes.fromhex("0014074000"), 14_074_000),
        (bytes.fromhex("0000000000"), 0),
        (bytes.fromhex("9999999999"), 9_999_999_999),
        (b"", 0),
    ],
)
def test_decode_bcd(data: bytes, value: int) -> None:
    assert ys.decode_bcd(data) == value


@pytest.mark.parametrize("bad", ["001A074000", "00F0000000"])
def test_decode_bcd_rejects_invalid_nibbles(bad: str) -> None:
    with pytest.raises(FrameError, match="BCD"):
        ys.decode_bcd(bytes.fromhex(bad))


def test_bcd_helper_round_trip() -> None:
    assert ys.decode_bcd(bcd(50_313_000)) == 50_313_000
    with pytest.raises(ValueError, match="too large"):
        bcd(10**10)


def test_is_valid_frame() -> None:
    assert ys.is_valid_frame(make_ft4222_frame())
    assert not ys.is_valid_frame(make_ft4222_frame(sync=b"\x00\x00\x00\x00"))
    assert not ys.is_valid_frame(make_ft4222_frame()[:-1])


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"", "0 bytes"),
        (make_ft4222_frame()[:4095], "4095 bytes"),
        (make_ft4222_frame() + b"\x00", "4097 bytes"),
        (make_ft4222_frame(sync=b"\xff\x01\xee\x00"), "sync"),
        (make_ft4222_frame(span_index=10), "span index 10"),
        (make_ft4222_frame(span_index=255), "span index 255"),
        (make_ft4222_frame(vfo_a_hz=400_000, span_index=9), "below 0 Hz"),
    ],
)
def test_invalid_frames(raw: bytes, message: str) -> None:
    with pytest.raises(FrameError, match=message):
        ys.parse_frame(raw, FT710)


def test_invalid_vfo_bcd_raises_frame_error() -> None:
    raw = bytearray(make_ft4222_frame())
    raw[ys.DATA + ys.STATUS_VFO_A] = 0xAB
    with pytest.raises(FrameError, match="BCD"):
        ys.parse_frame(bytes(raw), FT710)


def test_low_edge_exactly_zero_is_allowed() -> None:
    parsed = ys.parse_frame(make_ft4222_frame(vfo_a_hz=500, span_index=0), FT710)
    assert parsed.spectrum.low_hz == 0


# --- verified on a real FT-710 (#111) ------------------------------------------------


def _with(frame: bytes, offset: int, value: bytes) -> bytes:
    buf = bytearray(frame)
    buf[ys.DATA + offset : ys.DATA + offset + len(value)] = value
    return bytes(buf)


@pytest.mark.parametrize(("byte32", "mode"), [(0x44, 0x07), (0x84, 0x0A), (0x04, 0x04)])
def test_span_index_is_low_nibble_in_every_mode(byte32: int, mode: int) -> None:
    raw = _with(make_ft4222_frame(scope_mode=mode), ys.STATUS_SPAN, bytes([byte32]))
    assert FT710.parse(raw).status.span_hz == 20_000


def test_fixed_mode_edges_use_reported_start_frequency() -> None:
    raw = make_ft4222_frame(vfo_a_hz=7_074_000, scope_mode=0x0A)
    raw = _with(raw, ys.STATUS_SPAN, bytes([0x84]))
    raw = _with(raw, ys.STATUS_SCOPE_START, (7_000_000).to_bytes(4, "big"))
    spec = FT710.parse(raw).spectrum
    assert (spec.low_hz, spec.high_hz) == (7_000_000, 7_020_000)


def test_cursor_mode_edges_stay_vfo_centred() -> None:
    raw = _with(make_ft4222_frame(vfo_a_hz=7_074_000, scope_mode=0x07), ys.STATUS_SPAN, b"\x44")
    spec = FT710.parse(raw).spectrum
    assert (spec.low_hz, spec.high_hz) == (7_064_000, 7_084_000)


def test_out_of_range_span_outside_center_needs_a_fallback() -> None:
    raw = _with(make_ft4222_frame(scope_mode=0x07), ys.STATUS_SPAN, b"\x4c")
    with pytest.raises(SpanUnavailable, match="Center mode"):
        FT710.parse(raw)
    parsed = ys.parse_frame(raw, FT710, span_fallback_hz=50_000)
    assert parsed.status.span_hz == 50_000


def test_frame_decoder_remembers_last_center_span() -> None:
    decoder = FrameDecoder(FT710)
    with pytest.raises(SpanUnavailable):
        decoder(_with(make_ft4222_frame(scope_mode=0x07), ys.STATUS_SPAN, b"\x4c"))
    assert decoder(make_ft4222_frame(span_index=5)).status.span_hz == 50_000
    assert decoder.last_span_hz == 50_000
    cursor = _with(make_ft4222_frame(scope_mode=0x07), ys.STATUS_SPAN, b"\x4c")
    assert decoder(cursor).status.span_hz == 50_000
