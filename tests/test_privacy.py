# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Privacy by design (GDPR, issue #142): the app talks only to N1MM+ and, if enabled,
its own remote-control port. No telemetry, update checks or other network use."""

from __future__ import annotations

import io
import re
import socket
from pathlib import Path
from typing import Any

import pytest

from n1mm_scope_bridge.cli import main

SRC = Path(__file__).resolve().parent.parent / "src" / "n1mm_scope_bridge"
FORBIDDEN = re.compile(
    r"^\s*(?:import|from)\s+(urllib|http|requests|httpx|aiohttp|ftplib|smtplib|xmlrpc|"
    r"webbrowser|ssl|asyncio|PySide6\.QtNetwork)\b",
    re.MULTILINE,
)
# Modules allowed to use sockets, and why.
SOCKET_USERS = {
    "n1mm.py": "UDP spectrum packets to the configured N1MM+ host",
    "control.py": "optional UDP remote control (off by default)",
    "gui/app.py": "self-test listener on 127.0.0.1",
    "gui/status.py": "socket.gethostname() only, to redact it from diagnostics",
}


def _modules() -> list[tuple[str, str]]:
    return [
        (p.relative_to(SRC).as_posix(), p.read_text(encoding="utf-8")) for p in SRC.rglob("*.py")
    ]


def test_no_http_or_telemetry_libraries() -> None:
    offenders = [name for name, text in _modules() if FORBIDDEN.search(text)]
    assert offenders == [], (
        f"network libraries need an approved issue + privacy notice: {offenders}"
    )


def test_only_known_modules_use_sockets() -> None:
    users = {
        name for name, text in _modules() if re.search(r"^\s*import socket\b", text, re.MULTILINE)
    }
    assert users <= set(SOCKET_USERS), f"unexpected socket use: {users - set(SOCKET_USERS)}"


def test_urls_open_only_on_user_request() -> None:
    openers = {name for name, text in _modules() if "QDesktopServices" in text}
    assert openers <= {"gui/main_window.py"}


def test_run_sends_only_to_the_configured_n1mm_host(monkeypatch: pytest.MonkeyPatch) -> None:
    connects: list[Any] = []
    sends: list[Any] = []
    original_sendto = socket.socket.sendto

    def record_connect(self: socket.socket, address: Any) -> None:
        connects.append(address)
        raise AssertionError(f"unexpected outbound connection to {address}")

    def record_sendto(self: socket.socket, data: bytes, *args: Any) -> int:
        sends.append(args[-1])
        return original_sendto(self, data, *args)

    monkeypatch.setattr(socket.socket, "connect", record_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", record_connect)
    monkeypatch.setattr(socket.socket, "sendto", record_sendto)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: record_connect(None, a))  # type: ignore[arg-type]

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        control_port = probe.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        port = rx.getsockname()[1]
        out, err = io.StringIO(), io.StringIO()
        code = main(
            [
                "run",
                "--emulator",
                "--duration",
                "0.6",
                "--rate",
                "10",
                "--port",
                str(port),
                "--control-port",
                str(control_port),
            ],
            out=out,
            err=err,
        )
    assert code == 0, err.getvalue()
    assert connects == []
    assert sends, "expected spectrum packets"
    assert {tuple(a[:2]) for a in sends} == {("127.0.0.1", port)}
