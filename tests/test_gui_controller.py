# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6", reason="GUI needs PySide6 (not available on free-threaded Python)")

from fakes import FakeApi
from frames import make_ft4222_frame
from pytestqt.qtbot import QtBot

from n1mm_scope_bridge.demo import DemoStream
from n1mm_scope_bridge.gui import controller as gc
from n1mm_scope_bridge.gui.controller import StreamController
from n1mm_scope_bridge.radios.base import ScopeStatus
from n1mm_scope_bridge.settings import Settings
from n1mm_scope_bridge.transport.ft4222 import Ft4222Error, Ft4222Reader, LibraryNotFound

pytestmark = pytest.mark.gui


@pytest.fixture
def listener() -> Iterator[socket.socket]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(5)
        yield rx


def settings_for(rx: socket.socket, **kw: Any) -> Settings:
    return Settings(n1mm_port=rx.getsockname()[1], rate_hz=10.0, **kw)


def demo_factory(_: Settings) -> gc.Source:
    stream = DemoStream(fps=50)
    return stream, stream.stop


def test_streams_demo_frames_and_reports(qtbot: QtBot, listener: socket.socket) -> None:
    ctl = StreamController(source_factory=demo_factory)
    statuses: list[ScopeStatus] = []
    ctl.status.connect(statuses.append)
    with qtbot.waitSignal(ctl.started, timeout=2000):
        assert ctl.start(settings_for(listener))
    assert ctl.running
    with qtbot.waitSignal(ctl.stats, timeout=2000) as stats:
        pass
    assert stats.args[0].frames_read > 0
    assert b"<Spectrum>" in listener.recvfrom(65535)[0]
    qtbot.waitUntil(lambda: bool(statuses), timeout=2000)
    assert statuses[-1].vfo_hz == 14_074_000
    with qtbot.waitSignal(ctl.stopped, timeout=6000) as stopped:
        ctl.stop()
    assert stopped.args == [""]
    assert not ctl.running
    assert not [t for t in threading.enumerate() if t.name.startswith("ft710-")]


def test_start_twice_is_harmless(qtbot: QtBot, listener: socket.socket) -> None:
    ctl = StreamController(source_factory=demo_factory)
    assert ctl.start(settings_for(listener))
    assert ctl.start(settings_for(listener))
    ctl.stop()
    ctl.stop()  # not running: no second signal, no error


def test_invalid_settings_are_reported(qtbot: QtBot) -> None:
    ctl = StreamController(source_factory=demo_factory)
    with qtbot.waitSignal(ctl.stopped, timeout=1000) as stopped:
        assert not ctl.start(Settings(n1mm_port=0))
    assert "n1mm_port" in stopped.args[0]
    assert not ctl.running


def test_source_factory_failure_is_reported(qtbot: QtBot) -> None:
    def missing(_: Settings) -> gc.Source:
        raise LibraryNotFound("Could not load FTDI's LibFT4222/D2XX libraries")

    ctl = StreamController(source_factory=missing)
    with qtbot.waitSignal(ctl.stopped, timeout=1000) as stopped:
        assert not ctl.start(Settings())
    assert stopped.args[0].startswith("Could not load FTDI")


def test_source_error_while_streaming(qtbot: QtBot, listener: socket.socket) -> None:
    def failing(_: Settings) -> gc.Source:
        def frames() -> Iterator[bytes]:
            yield make_ft4222_frame()
            raise Ft4222Error("FT4222_SPIMaster_SingleRead failed (FT_IO_ERROR)")

        return frames(), lambda: None

    ctl = StreamController(source_factory=failing)
    with qtbot.waitSignal(ctl.stopped, timeout=5000) as stopped:
        ctl.start(settings_for(listener))
    assert "FT_IO_ERROR" in stopped.args[0]
    assert not ctl.running


def test_finite_source_end_is_reported(qtbot: QtBot, listener: socket.socket) -> None:
    def finite(_: Settings) -> gc.Source:
        return [make_ft4222_frame()], lambda: None

    ctl = StreamController(source_factory=finite)
    with qtbot.waitSignal(ctl.stopped, timeout=5000) as stopped:
        ctl.start(settings_for(listener))
    assert "source ended" in stopped.args[0]


def test_radio_source_reports_missing_ftdi_folder(tmp_path: Path) -> None:
    with pytest.raises(LibraryNotFound, match="folder does not exist"):
        gc.radio_source(Settings(ftdi_lib_dir=str(tmp_path / "nope")))


def test_friendly_error() -> None:
    assert gc.friendly_error(OSError("port in use")) == "port in use"
    assert gc.friendly_error(KeyError("x")) == "Unexpected error: KeyError: 'x'"


def test_radio_source_builds_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []

    def fake_load_api(lib_dir: str | None) -> FakeApi:
        seen.append(lib_dir)
        return FakeApi()

    monkeypatch.setattr(gc, "load_api", fake_load_api)
    reader, close = gc.radio_source(Settings(device="FT4222 B"))
    assert seen == [None]
    assert isinstance(reader, Ft4222Reader)
    close()


def test_idle_poll_and_finish_are_noops(qtbot: QtBot) -> None:
    ctl = StreamController(source_factory=demo_factory)
    with qtbot.assertNotEmitted(ctl.stats), qtbot.assertNotEmitted(ctl.stopped):
        ctl._poll()
    assert ctl._finish() == ""


def test_preview_signal_runs_faster_than_n1mm_updates(
    qtbot: QtBot, listener: socket.socket
) -> None:
    """#126: the live display follows the radio's frame rate, not the N1MM+ send rate."""
    ctl = StreamController(source_factory=demo_factory)
    previews: list[object] = []
    sent: list[object] = []
    ctl.preview.connect(previews.append)
    ctl.frame.connect(sent.append)
    assert ctl.start(Settings(n1mm_port=listener.getsockname()[1], rate_hz=2.0))
    qtbot.waitUntil(lambda: len(previews) >= 20, timeout=5000)
    ctl.stop()
    assert len(previews) > 3 * max(1, len(sent))
