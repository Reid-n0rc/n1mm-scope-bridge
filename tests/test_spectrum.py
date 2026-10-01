# SPDX-License-Identifier: GPL-3.0-only
import dataclasses

import pytest

from n1mm_scope_bridge.spectrum import MAX_N1MM_LEVEL, SpectrumFrame


def frame(**kw: object) -> SpectrumFrame:
    args: dict[str, object] = {
        "low_hz": 14_000_000,
        "high_hz": 14_100_000,
        "levels": (0, 128, 255),
        "max_level": 255,
    }
    args.update(kw)
    return SpectrumFrame(**args)  # type: ignore[arg-type]


def test_valid_frame_and_span() -> None:
    f = frame()
    assert f.span_hz == 100_000
    assert f.levels == (0, 128, 255)


def test_frame_is_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        frame().low_hz = 1  # type: ignore[misc]


def test_boundaries_accepted() -> None:
    f = frame(low_hz=0, high_hz=1, levels=(MAX_N1MM_LEVEL,), max_level=MAX_N1MM_LEVEL)
    assert f.span_hz == 1


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"low_hz": -1}, "low_hz"),
        ({"high_hz": 14_000_000}, "greater than"),
        ({"high_hz": 13_000_000}, "greater than"),
        ({"max_level": 0}, "max_level"),
        ({"max_level": MAX_N1MM_LEVEL + 1}, "max_level"),
        ({"levels": ()}, "empty"),
        ({"levels": (0, 256)}, r"levels\[1\]"),
        ({"levels": (-1,)}, r"levels\[0\]"),
    ],
)
def test_invalid_frames_rejected(kw: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        frame(**kw)


def test_levels_must_be_tuple() -> None:
    with pytest.raises(TypeError, match="tuple"):
        frame(levels=[1, 2, 3])
