# SPDX-License-Identifier: GPL-3.0-only
import pytest

from n1mm_scope_bridge.radios import RADIOS, get_radio
from n1mm_scope_bridge.radios.ft710 import FT710


@pytest.mark.parametrize("key", ["ft710", "FT-710", "ft_710", "Ft710"])
def test_get_radio_normalizes(key: str) -> None:
    assert get_radio(key) is FT710


def test_get_radio_unknown_lists_supported() -> None:
    with pytest.raises(KeyError, match="supported: ft710"):
        get_radio("ic7300")


def test_registry_keys_match_profiles() -> None:
    assert all(key == profile.key for key, profile in RADIOS.items())


def test_ft710_profile_matches_wfview_rig_file() -> None:
    assert FT710.model == "FT-710"
    assert FT710.frame_size == 4096
    assert FT710.bins == 850  # SpectrumLenMax
    assert FT710.max_level == 255  # SpectrumAmpMax
    assert len(FT710.spans_hz) == 10
    assert FT710.spans_hz[0] == 1_000
    assert FT710.spans_hz[-1] == 1_000_000
    assert [code for code, _ in FT710.scope_modes] == list("0123456789A")
    assert FT710.scope_mode_name("A") == "Fixed (Normal)"
    assert FT710.scope_mode_name("Z") is None
