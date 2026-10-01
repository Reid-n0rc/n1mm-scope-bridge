# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from cliutil import cli


def test_list_radios() -> None:
    code, out, _ = cli("list-radios")
    assert code == 0
    assert "ft710" in out
    assert "FT-710" in out
