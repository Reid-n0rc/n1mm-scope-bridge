# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6", reason="GUI needs PySide6 (not available on free-threaded Python)")

from pytestqt.qtbot import QtBot

from n1mm_scope_bridge.control import ControlServer, request
from n1mm_scope_bridge.gui.main_window import MainWindow
from n1mm_scope_bridge.gui.remote import GuiRemote, RemoteControl, control_key
from n1mm_scope_bridge.settings import Settings

pytestmark = pytest.mark.gui


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Host:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.fail: Exception | None = None

    def remote_status(self) -> dict[str, Any]:
        self.calls.append(("status", threading.current_thread().name))
        if self.fail is not None:
            raise self.fail
        return {"streaming": False}

    def remote_start(self) -> None:
        self.calls.append(("start",))

    def remote_stop(self) -> None:
        self.calls.append(("stop",))

    def remote_set(self, name: str, value: str | float) -> None:
        self.calls.append(("set", name, value))


class FakeServer:
    def __init__(self, controller: Any, **kw: Any) -> None:
        self.kw = kw
        self.address = (kw["bind"], kw["port"])
        self.stopped = False

    def start(self) -> FakeServer:
        return self

    def stop(self) -> None:
        self.stopped = True


def in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except Exception as err:
            box["error"] = err

    t = threading.Thread(target=run, name="worker")
    t.start()
    return t, box


# --- control_key ---------------------------------------------------------------------


def test_control_key() -> None:
    assert control_key(Settings()) is None  # off by default
    on = Settings(control_enabled=True, control_allow="10.0.0.2, 10.0.0.3")
    assert control_key(on) == (True, 13070, "127.0.0.1", ("10.0.0.2", "10.0.0.3"))
    assert control_key(on.replace(control_allow="not-an-ip")) is None


# --- GuiRemote ---------------------------------------------------------------------------


def test_same_thread_calls_run_directly(qtbot: QtBot) -> None:
    host = Host()
    remote = GuiRemote(host)
    assert remote.status() == {"streaming": False}
    remote.start()
    remote.stop()
    remote.set_option("rate", 5.0)
    assert host.calls[1:] == [("start",), ("stop",), ("set", "rate", 5.0)]


def test_other_thread_calls_run_on_the_gui_thread(qtbot: QtBot) -> None:
    host = Host()
    remote = GuiRemote(host)
    remote.set_active(True)
    t, box = in_thread(remote.status)
    qtbot.waitUntil(lambda: "value" in box or "error" in box, timeout=3000)
    t.join(2)
    assert box["value"] == {"streaming": False}
    assert host.calls == [("status", threading.current_thread().name)]


def test_errors_are_handed_back_to_the_caller(qtbot: QtBot) -> None:
    host = Host()
    host.fail = ValueError("nope")
    remote = GuiRemote(host)
    remote.set_active(True)
    t, box = in_thread(remote.status)
    qtbot.waitUntil(lambda: "error" in box, timeout=3000)
    t.join(2)
    assert str(box["error"]) == "nope"


def test_busy_gui_thread_times_out_instead_of_deadlocking(qtbot: QtBot) -> None:
    host = Host()
    remote = GuiRemote(host, timeout=0.05)
    remote.set_active(True)
    t, box = in_thread(remote.status)
    t.join(2)  # the GUI thread is busy joining, so the job never runs in time
    assert "busy" in str(box["error"])
    # The late job still runs once the GUI thread is free (and is then ignored).
    qtbot.waitUntil(lambda: bool(host.calls), timeout=3000)
    remote.set_active(False)
    assert not remote.active


# --- RemoteControl -----------------------------------------------------------------------


def make_rc() -> tuple[RemoteControl, list[FakeServer], list[tuple[str, str]]]:
    made: list[FakeServer] = []
    logged: list[tuple[str, str]] = []

    def factory(controller: Any, **kw: Any) -> ControlServer:
        made.append(FakeServer(controller, **kw))
        return made[-1]  # type: ignore[return-value]

    rc = RemoteControl(GuiRemote(Host()), log=lambda lvl, m: logged.append((lvl, m)),
                       server_factory=factory)  # fmt: skip
    return rc, made, logged


def test_remote_control_lifecycle(qtbot: QtBot) -> None:
    rc, made, logged = make_rc()
    rc.apply(Settings(), {})
    assert (rc.server, rc.status_text, made) == (None, "Off", [])
    on = Settings(control_enabled=True)
    rc.apply(on, {})
    assert rc.status_text == "Listening on 127.0.0.1:13070"
    assert rc._remote.active
    assert made[0].kw["allow"] == ()
    rc.apply(on, {})  # unchanged: no restart
    assert len(made) == 1
    rc.apply(on.replace(control_port=13071), {})
    assert made[0].stopped
    assert len(made) == 2
    rc.apply(on.replace(control_port=1), {"control_port": "bad"})  # invalid: keep running
    assert len(made) == 2
    assert not made[1].stopped
    rc.apply(Settings(), {})
    assert made[1].stopped
    assert rc.status_text == "Off"
    assert ("info", "Remote control stopped") in logged


def test_remote_control_reports_listen_errors(qtbot: QtBot) -> None:
    logged: list[tuple[str, str]] = []

    def broken(controller: Any, **kw: Any) -> ControlServer:
        raise OSError("address in use")

    rc = RemoteControl(GuiRemote(Host()), log=lambda lvl, m: logged.append((lvl, m)),
                       server_factory=broken)  # fmt: skip
    rc.apply(Settings(control_enabled=True), {})
    assert rc.server is None
    assert "address in use" in rc.status_text
    assert logged[0][0] == "error"


# --- the window, end to end ---------------------------------------------------------------


@pytest.fixture
def listener() -> Iterator[socket.socket]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        yield rx


def ask(qtbot: QtBot, port: int, command: str) -> dict[str, Any]:
    t, box = in_thread(lambda: request(command, port=port, timeout=5))
    qtbot.waitUntil(lambda: "value" in box or "error" in box, timeout=8000)
    t.join(2)
    if "error" in box:
        raise box["error"]
    reply: dict[str, Any] = box["value"]
    return reply


def test_window_is_off_by_default(qtbot: QtBot) -> None:
    window = MainWindow(Settings(), save=lambda s, p: None, tray_available=lambda: False)
    qtbot.addWidget(window)
    assert window.remote.server is None
    assert window.settings_dialog.remote_status.text() == "Off"
    assert not window.remote._remote.active  # no polling while off


def test_window_serves_remote_control(
    qtbot: QtBot, listener: socket.socket, tmp_path: Path
) -> None:
    port = free_port()
    settings = Settings(
        emulator=True, control_enabled=True, control_port=port,
        n1mm_port=listener.getsockname()[1], rate_hz=10.0,
    )  # fmt: skip
    window = MainWindow(settings, save=lambda s, p: None, tray_available=lambda: False)
    qtbot.addWidget(window)
    assert window.settings_dialog.remote_status.text() == f"Listening on 127.0.0.1:{port}"
    assert ask(qtbot, port, "ping")["ok"]
    assert ask(qtbot, port, "status")["streaming"] is False
    assert ask(qtbot, port, "set name Shack 710")["ok"]
    assert window.source_name.text() == "Shack 710"
    assert not ask(qtbot, port, "set rate 50")["ok"]
    assert ask(qtbot, port, "set combine peak")["ok"]
    assert window.combine.currentData() == "peak"
    assert ask(qtbot, port, "set scaling 0.5")["ok"]
    assert ask(qtbot, port, "start")["ok"]
    qtbot.waitUntil(lambda: window.controller.running, timeout=3000)
    assert ask(qtbot, port, "set rate 5")["ok"]  # restarts the stream
    assert window.rate.value() == 10
    qtbot.waitUntil(lambda: window.model.stats is not None, timeout=5000)
    status = ask(qtbot, port, "status")
    assert status["streaming"] is True
    assert status["radio"] == "Shack 710"
    assert "sent" in status
    assert ask(qtbot, port, "stop")["ok"]
    assert not window.controller.running
    window.quit_app()
    assert window.remote.server is None


def test_remote_start_rejects_invalid_settings(qtbot: QtBot) -> None:
    window = MainWindow(Settings(), save=lambda s, p: None, tray_available=lambda: False)
    qtbot.addWidget(window)
    window.host.setText(" ")
    with pytest.raises(ValueError, match="n1mm_host"):
        window.remote_start()
    window.remote_stop()  # not streaming: no-op


def test_remote_status_reports_last_error(qtbot: QtBot) -> None:
    window = MainWindow(Settings(), save=lambda s, p: None, tray_available=lambda: False)
    qtbot.addWidget(window)
    window.model.last_error = "radio gone"
    assert window.remote_status()["error"] == "radio gone"
