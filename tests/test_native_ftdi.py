# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The real native boundary: FTDI's own LibFT4222 and D2XX DLLs (#37).

CI (Windows) downloads them with scripts/fetch_ftdi.py and sets
N1MM_BRIDGE_FTDI_DIR. Runners have no FT-710 attached, so these tests cover
loading (including the ftd2xx.dll dependency), symbol resolution, ctypes
signatures, and the no-device error path. Streaming data is covered by the
emulator (docs/emulator.md).
"""

from __future__ import annotations

import ctypes
import os
import sys

import pytest

from n1mm_scope_bridge.cli import main
from n1mm_scope_bridge.transport import ft4222 as ft
from n1mm_scope_bridge.transport.ft4222 import CtypesApi, DeviceNotFound, Ft4222Reader, load_api

FTDI_DIR = os.environ.get("N1MM_BRIDGE_FTDI_DIR", "")

pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(
        not FTDI_DIR,
        reason="set N1MM_BRIDGE_FTDI_DIR to a folder with FTDI's LibFT4222 and ftd2xx (CI Windows)",
    ),
]

FUNCTIONS = (
    "_open", "_close", "_timeouts", "_latency", "_uninit", "_spi_init", "_read", "_clock",
)  # fmt: skip


def test_real_libraries_load_and_bind() -> None:
    api = load_api(FTDI_DIR)
    assert isinstance(api, CtypesApi)
    for attr in FUNCTIONS:
        fn = getattr(api, attr)
        assert fn.restype is ctypes.c_uint32, attr
        assert fn.argtypes, attr
    if sys.platform == "win32":
        # The exports really are the stdcall (WinDLL) flavour wfview calls.
        assert isinstance(api._open, ctypes.WinDLL._FuncPtr)  # type: ignore[attr-defined]


def test_no_device_is_reported_as_not_found() -> None:
    api = load_api(FTDI_DIR)
    status, _ = api.open_ex(ft.DEFAULT_DESCRIPTION)
    assert ft.status_name(status) == "FT_DEVICE_NOT_FOUND"
    with pytest.raises(DeviceNotFound, match="FT_DEVICE_NOT_FOUND"):
        Ft4222Reader(api).open()


def test_cli_probe_reports_friendly_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["probe", "--ftdi-lib-dir", FTDI_DIR]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: Could not open 'FT4222 A'")
    assert "Traceback" not in err
