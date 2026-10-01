# SPDX-License-Identifier: GPL-3.0-only
"""Registry of supported radios."""

from __future__ import annotations

from n1mm_scope_bridge.radios.base import RadioProfile
from n1mm_scope_bridge.radios.ft710 import FT710

RADIOS: dict[str, RadioProfile] = {profile.key: profile for profile in (FT710,)}


def get_radio(key: str) -> RadioProfile:
    """Look up a radio by its CLI key (case-insensitive, dashes ignored)."""
    normalized = key.lower().replace("-", "").replace("_", "")
    try:
        return RADIOS[normalized]
    except KeyError:
        known = ", ".join(sorted(RADIOS))
        raise KeyError(f"unknown radio {key!r}; supported: {known}") from None
