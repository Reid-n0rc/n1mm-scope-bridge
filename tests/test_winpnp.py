# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from collections.abc import Sequence

import pytest
from fakes import FakeApi

from n1mm_scope_bridge.transport import winpnp
from n1mm_scope_bridge.transport.ft4222 import DeviceNotFound, Ft4222Reader

STARTED = """Microsoft PnP Utility

Instance ID:                USB\\VID_0403&PID_601C&MI_00\\6&1a2b3c&0&0000
Device Description:         FT4222H Interface A
Class Name:                 USB
Manufacturer Name:          FTDI
Status:                     Started
Driver Name:                oem42.inf

Instance ID:                USB\\VID_10C4&PID_EA70\\0001
Device Description:         CP2105 Dual USB to UART Bridge Controller
Status:                     Started
Driver Name:                oem7.inf
"""

NO_DRIVER = """Microsoft PnP Utility

Instance ID:                USB\\VID_0403&PID_601C&MI_00\\6&1a2b3c&0&0000
Device Description:         FT4222H
Status:                     Problem
Problem Code:               28 (0x1C) [CM_PROB_FAILED_INSTALL]
"""

OTHER_ONLY = """Instance ID: USB\\VID_10C4&PID_EA70\\0001
Status: Started
Driver Name: oem7.inf
"""


def runner(output: str, code: int = 0) -> winpnp.Runner:
    def run(cmd: Sequence[str]) -> tuple[int, str]:
        assert cmd[1:] == ["/enum-devices", "/connected"]
        return code, output

    return run


@pytest.mark.parametrize(
    ("output", "state"),
    [(STARTED, "ok"), (NO_DRIVER, "no-driver"), (OTHER_ONLY, "not-present"), ("", "not-present")],
)
def test_driver_state(output: str, state: str) -> None:
    assert winpnp.ft4222_driver_state(runner(output), windows=True) == state


def test_unknown_when_not_windows_or_pnputil_fails() -> None:
    assert winpnp.ft4222_driver_state(runner(NO_DRIVER), windows=False) == "unknown"
    assert winpnp.ft4222_driver_state(runner(NO_DRIVER, code=1), windows=True) == "unknown"

    def boom(cmd: Sequence[str]) -> tuple[int, str]:
        raise OSError("pnputil missing")

    assert winpnp.ft4222_driver_state(boom, windows=True) == "unknown"


def test_unclear_device_state_is_unknown() -> None:
    odd = "Instance ID: USB\\VID_0403&PID_601C\\x\nStatus: Disconnected\nDriver Name: oem1.inf\n"
    assert winpnp.ft4222_driver_state(runner(odd), windows=True) == "unknown"


def test_parse_devices_splits_blocks() -> None:
    devices = winpnp.parse_devices(STARTED)
    assert len(devices) == 2
    assert devices[0]["driver name"] == "oem42.inf"
    assert devices[1]["device description"].startswith("CP2105")


def test_driver_hint_only_when_driver_missing() -> None:
    assert winpnp.driver_hint(runner(NO_DRIVER), windows=True) == winpnp.DRIVER_HINT
    assert winpnp.driver_hint(runner(STARTED), windows=True) == ""
    assert winpnp.driver_hint(runner(NO_DRIVER), windows=False) == ""


def test_device_not_found_includes_driver_hint() -> None:
    reader = Ft4222Reader(FakeApi(open=2), driver_hint=lambda: winpnp.DRIVER_HINT)
    with pytest.raises(DeviceNotFound, match="no working FTDI USB driver"):
        reader.open()
    plain = Ft4222Reader(FakeApi(open=2), driver_hint=lambda: "")
    with pytest.raises(DeviceNotFound) as exc:
        plain.open()
    assert "FTDI USB driver for it" not in str(exc.value)
