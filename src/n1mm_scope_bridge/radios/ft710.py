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
#
# Modified by Reid Crowe, N0RC, 2026-10-01: span and scope-mode tables from rigs/FT-710.rig
#   converted from Qt INI format into a Python RadioProfile.
"""Yaesu FT-710 profile.

Span and scope-mode tables are from wfview's rigs/FT-710.rig (see the header
above and THIRD_PARTY.md).
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
