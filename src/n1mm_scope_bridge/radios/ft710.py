# SPDX-License-Identifier: GPL-3.0-only
"""Yaesu FT-710 profile.

Span and scope-mode tables are from wfview's rigs/FT-710.rig
(https://gitlab.com/eliggett/wfview), Copyright 2017-2026 Elliott H. Liggett
W6EL and Phil E. Taylor M0VSE, GPLv3.
"""

from __future__ import annotations

from n1mm_scope_bridge.radios import yaesu_scope
from n1mm_scope_bridge.radios.base import RadioProfile

FT710 = RadioProfile(
    key="ft710",
    model="FT-710",
    transport="ft4222",
    frame_size=yaesu_scope.FRAME_SIZE,
    bins=yaesu_scope.BINS,
    max_level=255,
    spans_hz=(
        1_000,
        2_000,
        5_000,
        10_000,
        20_000,
        50_000,
        100_000,
        200_000,
        500_000,
        1_000_000,
    ),
    scope_modes=(
        ("0", "3DSS Center"),
        ("1", "3DSS Cursor"),
        ("2", "3DSS Fixed"),
        ("3", "Center (Expand)"),
        ("4", "Center (Normal)"),
        ("5", "Center (Expand)"),
        ("6", "Cursor (Expand)"),
        ("7", "Cursor (Normal)"),
        ("8", "Cursor (Expand)"),
        ("9", "Fixed (Expand)"),
        ("A", "Fixed (Normal)"),
    ),
    parser=yaesu_scope.parse_frame,
)
