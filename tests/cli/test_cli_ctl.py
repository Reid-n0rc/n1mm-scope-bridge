# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

from cliutil import FIXTURE, cli

from n1mm_scope_bridge import control as ctl


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_ctl_reports_no_bridge() -> None:
    code, _, err = cli("ctl", "--port", str(free_port()), "--timeout", "0.3", "status")
    assert code == 1
    assert "No reply from n1mm-scope-bridge at 127.0.0.1:" in err


def test_run_with_remote_control_stop_start_set(tmp_path: Path) -> None:
    """Headless run with --control-port, driven by `ctl` from another thread."""
    port = free_port()
    replies: dict[str, dict[str, object]] = {}
    done = threading.Event()

    def drive() -> None:
        for _ in range(50):
            try:
                ctl.request("ping", port=port, timeout=0.2)
                break
            except OSError:
                continue
        for name, cmd in [
            ("stop", "stop"),
            ("set", "set rate 5"),
            ("start", "start"),
            ("status", "status"),
        ]:
            code, out, _ = cli("ctl", "--port", str(port), *cmd.split())
            replies[name] = json.loads(out) | {"exit": code}
        done.set()

    t = threading.Thread(target=drive)
    t.start()
    code, _, err = cli(
        "run", "--replay", str(FIXTURE), "--loop", "--duration", "3", "--port", str(free_port()),
        "--rate", "10", "--control-port", str(port),
    )  # fmt: skip
    t.join(5)
    assert done.is_set()
    assert code == 0, err
    assert f"Remote control listening on 127.0.0.1:{port}" in err
    assert replies["stop"]["streaming"] is False
    assert replies["set"] == {"ok": True, "rate": 5.0, "exit": 0}
    assert replies["start"]["streaming"] is True
    assert replies["status"]["rate"] == 5.0


def test_ctl_exit_code_follows_ok() -> None:
    port = free_port()
    code_holder: list[int] = []

    def drive() -> None:
        for _ in range(50):
            try:
                ctl.request("ping", port=port, timeout=0.2)
                break
            except OSError:
                continue
        code, _, _ = cli("ctl", "--port", str(port), "set", "rate", "99")
        code_holder.append(code)

    t = threading.Thread(target=drive)
    t.start()
    cli("run", "--replay", str(FIXTURE), "--loop", "--duration", "1.5", "--port", str(free_port()),
        "--control-port", str(port))  # fmt: skip
    t.join(5)
    assert code_holder == [1]


def test_control_port_in_use_is_reported() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as busy:
        busy.bind(("127.0.0.1", 0))
        port = busy.getsockname()[1]
        code, _, err = cli("run", "--replay", str(FIXTURE), "--control-port", str(port))
    assert code == 1
    assert "Could not start remote control on 127.0.0.1:" in err


def test_remote_control_is_off_by_default() -> None:
    code, _, err = cli(
        "run", "--replay", str(FIXTURE), "--duration", "0.3", "--port", str(free_port())
    )
    assert code == 0
    assert "Remote control" not in err
    assert not [t for t in threading.enumerate() if t.name == "control"]
