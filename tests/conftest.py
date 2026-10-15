# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import gc
import os
import re
import socket
import sys
from collections.abc import Generator, Iterator

import pytest

# GUI tests run headless everywhere (CI and local) unless a platform is forced.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# A quarantine must name the open issue that tracks the flaky test (#222).
_ISSUE_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/issues/\d+")
_FLAKY_USAGE = "use @pytest.mark.flaky(reruns=1, reason=<GitHub issue URL>)"


def _check_quarantine(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep reruns narrow (#222): one rerun, gui tests only, each one tracked.

    Raises ``pytest.UsageError`` for a suite-wide rerun option or a ``flaky``
    marker that is not exactly ``flaky(reruns=1, reason=<issue URL>)`` on a
    ``gui`` test.
    """
    for option in ("reruns", "force_reruns"):
        if config.getoption(option, default=None):
            raise pytest.UsageError(f"--{option.replace('_', '-')} is not allowed: {_FLAKY_USAGE}")
    for item in items:
        marker = item.get_closest_marker("flaky")
        if marker is None:
            continue
        where = f"{item.nodeid}: flaky quarantine"
        if item.get_closest_marker("gui") is None:
            raise pytest.UsageError(f"{where} is for gui tests only")
        if marker.args or set(marker.kwargs) != {"reruns", "reason"}:
            raise pytest.UsageError(f"{where}: {_FLAKY_USAGE}")
        reruns = marker.kwargs["reruns"]
        if isinstance(reruns, bool) or reruns != 1:
            raise pytest.UsageError(f"{where} allows exactly one rerun, not {reruns!r}")
        if not _ISSUE_URL.search(str(marker.kwargs["reason"])):
            raise pytest.UsageError(f"{where}: reason must link the tracking issue")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Check flaky quarantines; hardware tests run only with N1MM_BRIDGE_HARDWARE=1."""
    _check_quarantine(config, items)
    if os.environ.get("N1MM_BRIDGE_HARDWARE") == "1":
        return
    skip = pytest.mark.skip(reason="set N1MM_BRIDGE_HARDWARE=1 with an FT-710 connected")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> Generator[None, object, object]:
    """Collect cyclic garbage on the main thread before each GUI test (#217)."""
    if "gui" in item.keywords:
        gc.collect()
    return (yield)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item: pytest.Item) -> Generator[None, object, object]:
    """Collect cyclic garbage on the main thread after each GUI test (#217).

    This wrapper sits outside pytest-qt's, so it runs after pytest-qt has closed
    the test's widgets with ``deleteLater()``. Those deletes never run outside an
    event loop, so they are flushed here first. A QObject left to a later
    collection could be deleted on a pipeline thread instead, off the GUI
    thread, which crashed Windows CI with an access violation.
    """
    result = yield
    if "gui" in item.keywords:
        qtcore = sys.modules.get("PySide6.QtCore")  # absent: no QObjects (e.g. 3.14t)
        if qtcore is not None:
            qtcore.QCoreApplication.sendPostedEvents(None, qtcore.QEvent.Type.DeferredDelete)
        gc.collect()
    return result


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Tag a test that needed a rerun with a ``flaky_rerun`` JUnit property (#222).

    pytest-rerunfailures sets ``report.rerun`` to the attempt's rerun count.
    The final teardown report's properties land on that test's last JUnit
    testcase, which CI's job summary counts.
    """
    rerun = getattr(report, "rerun", 0)
    if report.when == "teardown" and rerun:
        report.user_properties.append(("flaky_rerun", rerun))


@pytest.fixture
def listener() -> Iterator[socket.socket]:
    """A loopback UDP socket standing in for N1MM+ (bind port 0, 5 s timeout)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(5)
        yield rx
