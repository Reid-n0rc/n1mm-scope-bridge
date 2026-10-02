# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import json
import socket
import threading
from typing import Any

import pytest

from n1mm_scope_bridge import __version__
from n1mm_scope_bridge import control as ctl


class FakeController:
    def __init__(self) -> None:
        self.streaming = True
        self.options: dict[str, Any] = {}
        self.fail: Exception | None = None

    def status(self) -> dict[str, Any]:
        return {"streaming": self.streaming}

    def start(self) -> None:
        self.streaming = True

    def stop(self) -> None:
        if self.fail:
            raise self.fail
        self.streaming = False

    def set_option(self, name: str, value: str | float) -> None:
        if name == "rate" and not 0 < float(value) <= 10:
            raise ValueError("rate must be more than 0 and at most 10")
        self.options[name] = value


# --- handle_command -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ping", {"ok": True, "version": __version__}),
        ("PING  ", {"ok": True, "version": __version__}),
        ("status", {"ok": True, "streaming": True}),
        ("stop", {"ok": True, "streaming": False}),
        ("set rate 5", {"ok": True, "rate": 5.0}),
        ("set combine PEAK", {"ok": True, "combine": "peak"}),
        ("set name Shack FT-710", {"ok": True, "name": "Shack FT-710"}),
        ("set scaling 0.25", {"ok": True, "scaling": 0.25}),
    ],
)
def test_commands(text: str, expected: dict[str, Any]) -> None:
    assert ctl.handle_command(text, FakeController()) == expected


def test_start_after_stop() -> None:
    c = FakeController()
    ctl.handle_command("stop", c)
    assert ctl.handle_command("start", c) == {"ok": True, "streaming": True}


def test_help_lists_every_command() -> None:
    reply = ctl.handle_command("help", FakeController())
    assert reply["ok"]
    for name in ctl.COMMANDS:
        assert name in reply["help"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty command"),
        ("transmit", "unknown command 'transmit'"),
        ("set", "usage"),
        ("set rate", "usage"),
        ("set frequency 14074000", "cannot set 'frequency'"),
        ("set rate fast", "rate must be a number"),
        ("set rate 50", "at most 10"),
        ("set combine median", "combine must be one of"),
    ],
)
def test_errors(text: str, message: str) -> None:
    reply = ctl.handle_command(text, FakeController())
    assert reply["ok"] is False
    assert message in reply["error"]


def test_controller_os_error_is_reported() -> None:
    c = FakeController()
    c.fail = OSError("port in use")
    assert ctl.handle_command("stop", c) == {"ok": False, "error": "port in use"}


def test_no_command_can_change_radio_state() -> None:
    assert set(ctl.COMMANDS) == {"ping", "help", "status", "start", "stop", "set"}
    assert set(ctl.SETTABLE) == {"name", "rate", "combine", "scaling"}


# --- addresses ----------------------------------------------------------------------


def test_parse_allow_and_loopback() -> None:
    assert ctl.parse_allow("192.168.1.20, 10.0.0.5 ::1") == ("192.168.1.20", "10.0.0.5", "::1")
    assert ctl.parse_allow("") == ()
    with pytest.raises(ValueError, match="does not appear to be an IPv4 or IPv6 address"):
        ctl.parse_allow("not-an-ip")
    assert ctl.is_loopback("127.0.0.1")
    assert ctl.is_loopback("::1")
    assert not ctl.is_loopback("192.168.1.20")


# --- server ---------------------------------------------------------------------------


def no_control_thread() -> bool:
    return not [t for t in threading.enumerate() if t.name == "control"]


def test_server_round_trip_on_loopback() -> None:
    c = FakeController()
    with ctl.ControlServer(c, port=0) as server:
        assert server.address[0] == "127.0.0.1"
        port = server.address[1]
        assert ctl.request("status", port=port) == {"ok": True, "streaming": True}
        assert ctl.request("set rate 3", port=port) == {"ok": True, "rate": 3.0}
    assert c.options == {"rate": 3.0}
    assert no_control_thread()


def test_server_rejects_oversized_requests() -> None:
    with ctl.ControlServer(FakeController(), port=0) as server:
        reply = ctl.request("x" * (ctl.MAX_REQUEST + 10), port=server.address[1])
    assert reply == {"ok": False, "error": "command too long"}


def test_server_ignores_addresses_not_allowed() -> None:
    # Bound to loopback, but only 10.9.9.9 may send: our 127.0.0.1 request is dropped.
    server = ctl.ControlServer(FakeController(), port=0, bind="127.0.0.1", allow=())
    server._allowed = {"10.9.9.9"}
    with server:
        with pytest.raises(TimeoutError):
            ctl.request("status", port=server.address[1], timeout=0.5)
        assert server.ignored == 1


def test_non_loopback_bind_requires_allow_list() -> None:
    with pytest.raises(ValueError, match="allow-list"):
        ctl.ControlServer(FakeController(), port=0, bind="0.0.0.0")


def test_reply_is_one_json_line() -> None:
    with (
        ctl.ControlServer(FakeController(), port=0) as server,
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s,
    ):
        s.settimeout(2)
        s.sendto(b"ping", server.address)
        data = s.recv(65535)
    assert b"\n" not in data
    assert json.loads(data)["ok"] is True


def test_logs_requests() -> None:
    lines: list[str] = []
    with ctl.ControlServer(FakeController(), port=0, log=lines.append) as server:
        ctl.request("ping", port=server.address[1])
    assert lines
    assert "ok=True" in lines[0]


def test_stop_without_start_is_safe() -> None:
    ctl.ControlServer(FakeController(), port=0).stop()
    assert no_control_thread()
