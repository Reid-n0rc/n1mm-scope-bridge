# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
import pytest

from n1mm_scope_bridge.demo import build_frame, demo_frames, encode_bcd
from n1mm_scope_bridge.radios import yaesu_scope as ys
from n1mm_scope_bridge.radios.ft710 import FT710


def test_encode_bcd_round_trip() -> None:
    assert encode_bcd(14_074_000) == bytes.fromhex("0014074000")
    assert ys.decode_bcd(encode_bcd(9_999_999_999)) == 9_999_999_999


@pytest.mark.parametrize("value", [-1, 10**10])
def test_encode_bcd_rejects_out_of_range(value: int) -> None:
    with pytest.raises(ValueError, match="BCD"):
        encode_bcd(value)


def test_build_frame_parses_back() -> None:
    shown = bytes(range(256)) * 3 + bytes(82)
    parsed = FT710.parse(build_frame(shown, vfo_a_hz=7_030_000, span_index=3, scope_mode=0x07))
    assert parsed.spectrum.levels == tuple(shown)
    assert parsed.status.vfo_hz == 7_030_000
    assert parsed.status.span_hz == 10_000
    assert parsed.status.mode_family == "cursor"


def test_build_frame_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="850"):
        build_frame(b"\x00", vfo_a_hz=1_000_000, span_index=0)


def test_demo_frames_are_deterministic_and_parse() -> None:
    a, b = demo_frames(3), demo_frames(3)
    assert a == b
    parsed = [FT710.parse(f) for f in a]
    assert all(p.status.mode_family == "center" for p in parsed)
    assert max(parsed[0].spectrum.levels) > 60  # signals stand out of the noise
    assert min(parsed[0].spectrum.levels) >= 18
    assert demo_frames(1, seed=1) != demo_frames(1, seed=2)


def test_demo_frames_needs_positive_count() -> None:
    with pytest.raises(ValueError, match="count"):
        demo_frames(0)
