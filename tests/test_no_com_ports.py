# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The bridge must NEVER open a COM port (maintainer requirement, #62).

N1MM+ needs both FT-710 COM ports: Enhanced (CAT) and Standard (PTT/keying).
Opening either, even briefly, can break N1MM+'s CAT link or toggle DTR/RTS
and key the transmitter. Everything else (the scope stream, UDP control #30)
uses the FT4222 device and UDP sockets only.
"""

from __future__ import annotations

import builtins
import os
import re
import socket
from pathlib import Path
from typing import Any

import pytest
from cliutil import cli

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "n1mm_scope_bridge"
SERIAL_API = re.compile(
    r"\bimport serial\b|\bfrom serial\b|pyserial|CreateFile[AW]?\b|SetCommState|"
    r"\\\\\.\\\\COM|[\"']COM[0-9]|/dev/tty|termios",
    re.IGNORECASE,
)
COM_PATH = re.compile(r"(^|[\\/.])COM[0-9]+$|^/dev/tty", re.IGNORECASE)


@pytest.mark.parametrize(
    "path",
    sorted(p for p in PACKAGE.rglob("*.py")),
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_no_serial_port_code_in_the_package(path: Path) -> None:
    hits = SERIAL_API.findall(path.read_text(encoding="utf-8"))
    assert not hits, f"{path.name} contains serial-port code: {hits}"


def test_runtime_never_opens_a_com_port_even_with_udp_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    real_open, real_os_open = builtins.open, os.open

    def guard(name: Any) -> None:
        if isinstance(name, str | os.PathLike) and COM_PATH.search(os.fspath(name)):
            opened.append(os.fspath(name))

    def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        guard(file)
        return real_open(file, *args, **kwargs)

    def guarded_os_open(path: Any, *args: Any, **kwargs: Any) -> int:
        guard(path)
        return real_os_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        control_port = str(s.getsockname()[1])
    code, _, err = cli(
        "run", "--scenario", "mode-change", "--duration", "1.5", "--port", "9",
        "--control-port", control_port,
    )  # fmt: skip
    assert code == 0, err
    assert opened == []


def test_guard_pattern_matches_com_devices() -> None:
    for name in ("COM3", r"\\.\COM12", "/dev/ttyUSB0"):
        assert COM_PATH.search(name)
    for name in ("settings.json", "capture.cap", "commands.py"):
        assert not COM_PATH.search(name)
