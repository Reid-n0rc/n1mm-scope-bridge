# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Opt-in check against a real FT-710 on Windows: N1MM_BRIDGE_HARDWARE=1."""

from __future__ import annotations

import os

import pytest

from n1mm_scope_bridge.radios.ft710 import FT710
from n1mm_scope_bridge.transport.ft4222 import Ft4222Reader, load_api


@pytest.mark.hardware
def test_reads_and_parses_ten_frames_from_a_real_ft710() -> None:
    reader = Ft4222Reader(load_api(os.environ.get("N1MM_BRIDGE_FTDI_DIR")))
    frames = []
    for raw in reader:
        frames.append(FT710.parse(raw))
        if len(frames) == 10:
            reader.stop()
    assert len(frames) == 10
    status = frames[-1].status
    print(f"VFO-A {status.vfo_hz} Hz, span {status.span_hz} Hz, mode {status.mode_name}")
    print(f"resyncs={reader.resyncs} reinits={reader.reinits}")
