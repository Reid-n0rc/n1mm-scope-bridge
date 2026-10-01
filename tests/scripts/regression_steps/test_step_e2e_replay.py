# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import pytest
from regression_core import MIN_PACKETS, CheckFailed
from stepload import SPECTRUM, load_step, udp_runner

e2e = load_step("60_e2e_replay")


def test_e2e_replay_accepts_valid_packets() -> None:
    e2e.e2e_replay(udp_runner([SPECTRUM] * MIN_PACKETS))


@pytest.mark.parametrize(
    ("packets", "code", "message"),
    [
        ([SPECTRUM] * 6, 3, "exited 3"),
        ([SPECTRUM] * 2, 0, "got 2 packets"),
        ([b"<Spectrum>"] * 6, 0, "invalid"),
        ([b"<Other/>"] * 6, 0, "N1MM <Spectrum> format"),
    ],
)
def test_e2e_replay_failures(packets: list[bytes], code: int, message: str) -> None:
    with pytest.raises(CheckFailed, match=message):
        e2e.e2e_replay(udp_runner(packets, code))
