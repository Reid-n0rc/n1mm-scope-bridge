# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import io
import threading
from collections.abc import Iterator

import pytest
from frames import make_ft4222_frame

from n1mm_scope_bridge.cli.session import Source, StreamSession
from n1mm_scope_bridge.settings import Settings
from n1mm_scope_bridge.transport.ft4222 import Ft4222Error

SETTINGS = Settings(n1mm_port=9, rate_hz=10.0)  # discard port; nothing listens


def endless() -> Source:
    stop = threading.Event()

    def frames() -> Iterator[bytes]:
        while not stop.wait(0.01):
            yield make_ft4222_frame()

    return frames(), stop.set


def finite() -> Source:
    return [make_ft4222_frame()] * 3, lambda: None


def failing() -> Source:
    def frames() -> Iterator[bytes]:
        yield make_ft4222_frame()
        raise Ft4222Error("FT4222_SPIMaster_SingleRead failed (FT_IO_ERROR)")

    return frames(), lambda: None


def test_status_before_start_and_while_streaming() -> None:
    s = StreamSession(SETTINGS, endless, io.StringIO())
    assert s.status()["streaming"] is False
    s.start()
    s.start()  # already streaming: no second pipeline
    threading.Event().wait(0.3)
    info = s.status()
    assert info["streaming"] is True
    assert info["vfo_hz"] == 14_074_000
    assert info["sent"] >= 1
    s.stop()
    assert s.status()["streaming"] is False


def test_finite_source_ends_wait_without_keep_alive() -> None:
    s = StreamSession(SETTINGS, finite, io.StringIO())
    s.start()
    s.wait(duration=5)
    assert s.status()["streaming"] is False


def test_stream_error_is_raised_from_wait() -> None:
    s = StreamSession(SETTINGS, failing, io.StringIO())
    s.start()
    with pytest.raises(Ft4222Error, match="FT_IO_ERROR"):
        s.wait(duration=5)


def test_keep_alive_waits_while_stopped_until_duration() -> None:
    s = StreamSession(SETTINGS, finite, io.StringIO(), keep_alive=True)
    s.start()
    s.wait(duration=0.6)  # source ends, then idles until the deadline
    assert s.status()["streaming"] is False


def test_wait_without_start_returns_immediately() -> None:
    StreamSession(SETTINGS, endless, io.StringIO()).wait(duration=None)


def test_set_option_restarts_and_validates() -> None:
    s = StreamSession(SETTINGS, endless, io.StringIO())
    s.set_option("combine", "peak")  # not streaming: just stored
    assert s.settings.combine == "peak"
    s.start()
    s.set_option("rate", 5.0)
    assert s.status()["streaming"] is True
    assert s.settings.rate_hz == 5.0
    with pytest.raises(ValueError, match="at most 10"):
        s.set_option("rate", 99.0)
    with pytest.raises(ValueError, match="cannot set"):
        s.set_option("port", 1.0)
    s.stop()


def test_ctrl_c_stops_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    s = StreamSession(SETTINGS, endless, io.StringIO())
    s.start()

    def interrupt(*_: object, **__: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("n1mm_scope_bridge.cli.session.format_status", interrupt)
    s.wait(duration=None)
    assert s.status()["streaming"] is False
