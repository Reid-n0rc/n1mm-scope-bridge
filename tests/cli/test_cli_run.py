# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import socket
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from cliutil import FIXTURE, cli
from fakes import FakeApi
from frames import make_ft4222_frame

from n1mm_scope_bridge import settings as st
from n1mm_scope_bridge.transport.replay import CaptureWriter


def test_run_replay_streams_to_n1mm(listener: socket.socket) -> None:
    port = listener.getsockname()[1]
    code, _, err = cli(
        "run", "--replay", str(FIXTURE), "--loop", "--duration", "0.6",
        "--port", str(port), "--rate", "10", "--name", "Shack FT-710",
    )  # fmt: skip
    assert code == 0
    root = ET.fromstring(listener.recvfrom(65535)[0])
    assert root.findtext("Name") == "Shack FT-710"
    assert root.findtext("DataCount") == "850"
    assert "Streaming FT-710 to N1MM+ at 127.0.0.1:" in err
    assert "VFO 14.074000 MHz" in err


def test_run_radio_streams_with_fake_device(listener: socket.socket) -> None:
    port = listener.getsockname()[1]
    api = FakeApi(repeat=make_ft4222_frame())
    code, _, _ = cli("run", "--duration", "0.4", "--port", str(port), "--rate", "10", api=api)
    assert code == 0
    assert ET.fromstring(listener.recvfrom(65535)[0]).findtext("LowScopeFrequency") == "14024"


def test_run_reports_missing_ftdi_library() -> None:
    code, _, err = cli("run", "--duration", "0.1")
    assert code == 1
    assert err.startswith("error: Could not load FTDI")
    assert "Traceback" not in err


def test_run_rejects_capture_from_another_radio(tmp_path: Path) -> None:
    path = tmp_path / "other.cap"
    with path.open("wb") as fh:
        CaptureWriter(fh, "FTDX10", 4096)
    code, _, err = cli("run", "--replay", str(path))
    assert code == 1
    assert "recorded from a FTDX10, not a FT-710" in err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("run", "--radio", "ic7300"), "unknown radio"),
        (("run", "--replay", "missing.cap"), "missing.cap"),
        (("run", "--replay", str(FIXTURE), "--scaling", "0"), "scaling"),
        (("run", "--replay", str(FIXTURE), "--rate", "50"), "rate"),
        (("run", "--replay", str(FIXTURE), "--name", ""), "name"),
    ],
)
def test_run_user_errors(argv: tuple[str, ...], message: str) -> None:
    code, _, err = cli(*argv)
    assert code == 1
    assert message in err


def test_run_uses_saved_settings_with_cli_overrides(
    listener: socket.socket, tmp_path: Path
) -> None:
    port = listener.getsockname()[1]
    path = tmp_path / "settings.json"
    st.save(st.Settings(source_name="From GUI", n1mm_port=port, rate_hz=10.0), path)
    code, _, err = cli(
        "run", "--settings", str(path), "--replay", str(FIXTURE), "--loop", "--duration", "0.5"
    )
    assert code == 0, err
    assert ET.fromstring(listener.recvfrom(65535)[0]).findtext("Name") == "From GUI"
    code, _, _ = cli(
        "run", "--settings", str(path), "--name", "Override", "--replay", str(FIXTURE),
        "--loop", "--duration", "0.5",
    )  # fmt: skip
    assert code == 0
    names = set()
    listener.settimeout(0.2)
    try:
        while True:
            names.add(ET.fromstring(listener.recvfrom(65535)[0]).findtext("Name"))
    except TimeoutError:
        pass
    assert "Override" in names


def test_run_reports_settings_warnings_and_problems(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"n1mm_port": 0, "rate_hz": "x"}', encoding="utf-8")
    code, _, err = cli("run", "--settings", str(path), "--replay", str(FIXTURE))
    assert code == 1
    assert "warning: ignored invalid 'rate_hz'" in err
    assert "n1mm_port: port must be 1-65535" in err


def test_run_with_emulator(listener: socket.socket) -> None:
    port = listener.getsockname()[1]
    code, _, err = cli(
        "run", "--emulator", "--duration", "0.6", "--port", str(port), "--rate", "10"
    )
    assert code == 0, err
    assert ET.fromstring(listener.recvfrom(65535)[0]).findtext("DataCount") == "850"


def test_run_exits_1_when_the_radio_stream_fails() -> None:
    code, _, err = cli("run", "--scenario", "usb-unplug", "--duration", "10", "--port", "9")
    assert code == 1
    assert "error: FT4222_SPIMaster_SingleRead failed" in err


def test_run_prompts_for_center_and_confirms() -> None:
    code, _, err = cli(
        # mode-change cycles Center -> Cursor -> Fixed every 20 frames (3 s at 20 fps);
        # 8 s leaves slow CI runners time to return to Center.
        "run",
        "--scenario",
        "mode-change",
        "--duration",
        "8",
        "--port",
        "9",
        "--rate",
        "10",
    )
    assert code == 0
    assert "FT-710 scope left Center mode (Cursor (Normal))" in err
    assert "FT-710 scope is in Center mode: N1MM+ frequencies are exact." in err
