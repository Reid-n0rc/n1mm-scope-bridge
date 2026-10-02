# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Opt-in spike for #62 on a real FT-710: does a CAT port take the scope-mode command?

Run on the station PC with N1MM+ closed or connected to the *other* port:

    set N1MM_BRIDGE_HARDWARE=1
    set N1MM_BRIDGE_CAT_PORT=COM7        (the port to try, for example the Standard COM Port)
    uv run --with pyserial pytest tests/test_cat_hardware.py -s

SAFETY: DTR and RTS are forced low *before* the port opens, so a radio with
PTT/keying on RTS/DTR is never keyed. The only commands sent are the scope-mode
read (``SS06;``), Center (``SS0640000;``), and the restore of the mode read
first. UNVERIFIED (#62) until this passes on the maintainer's radio.
"""

from __future__ import annotations

import os

import pytest

from n1mm_scope_bridge.cat import CENTER, scope_mode_command

PORT = os.environ.get("N1MM_BRIDGE_CAT_PORT", "")


def _transact(ser: object, command: str) -> str:
    ser.reset_input_buffer()  # type: ignore[attr-defined]
    ser.write(command.encode("ascii"))  # type: ignore[attr-defined]
    return bytes(ser.read_until(b";")).decode("ascii", "replace")  # type: ignore[attr-defined]


@pytest.mark.hardware
@pytest.mark.skipif(not PORT, reason="set N1MM_BRIDGE_CAT_PORT to the COM port to test")
def test_scope_mode_set_and_restore_on_real_radio() -> None:
    serial = pytest.importorskip("serial")
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = (
        PORT,
        int(os.environ.get("N1MM_BRIDGE_CAT_BAUD", "38400")),
        1,
    )
    ser.dtr = False  # set before open(): never key PTT/CW through DTR/RTS
    ser.rts = False
    ser.open()
    try:
        before = _transact(ser, "SS06;")
        print(f"read: {before!r}")
        assert before.startswith("SS06"), "port does not answer the scope-mode read"
        original = before[4]
        _transact(ser, scope_mode_command(CENTER))
        assert _transact(ser, "SS06;")[4] == CENTER
        _transact(ser, scope_mode_command(original))
        assert _transact(ser, "SS06;")[4] == original
    finally:
        ser.close()
