# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""UDP remote control while the GUI runs (#77, built on #30's ``ControlServer``).

Off by default. When enabled in Settings → Remote control, the window serves
the same commands as ``n1mm-scope-bridge run --control-port`` with the same
security rules (loopback by default; a specific interface address plus an
allow-list for the LAN; never a wildcard bind). Commands arrive on the
control thread and are handed to the GUI thread, which owns every widget and
the stream controller; a command waits at most ``timeout`` seconds, so a busy
window answers with an error instead of deadlocking shutdown.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from PySide6.QtCore import QObject, QTimer

from n1mm_scope_bridge.control import ControlServer, parse_allow
from n1mm_scope_bridge.settings import Settings

T = TypeVar("T")
DEFAULT_TIMEOUT = 2.0
POLL_MS = 50


class RemoteHost(Protocol):
    """What the window exposes to remote commands (called on the GUI thread)."""

    def remote_status(self) -> dict[str, Any]:
        """Current state, as for the CLI's ``status`` reply."""

    def remote_start(self) -> None:
        """Start streaming (no-op if streaming); ValueError if settings are invalid."""

    def remote_stop(self) -> None:
        """Stop streaming; the window keeps running."""

    def remote_set(self, name: str, value: str | float) -> None:
        """Change name, rate, combine, or scaling; ValueError if invalid."""


class GuiRemote(QObject):
    """``BridgeController`` for ``ControlServer`` that runs every call on the GUI thread.

    The control thread never calls Qt: it queues a job in a Python deque and
    waits on a ``threading.Event``. A ``QTimer`` on the GUI thread drains the
    queue every ``POLL_MS``. (Emitting Qt signals or querying ``QThread``
    from a plain Python thread crashed PySide6 in testing.)
    """

    def __init__(
        self, host: RemoteHost, timeout: float = DEFAULT_TIMEOUT, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._timeout = timeout
        self._gui_ident = threading.get_ident()
        self._lock = threading.Lock()
        self._pending: deque[Callable[[], None]] = deque()
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._drain)

    def set_active(self, active: bool) -> None:
        """Poll for queued commands only while a control server is running."""
        if active:
            self._timer.start()
        else:
            self._timer.stop()
            self._drain()

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    return
                job = self._pending.popleft()
            job()

    def _invoke(self, fn: Callable[[], T]) -> T:
        if threading.get_ident() == self._gui_ident:
            return fn()
        done = threading.Event()
        box: dict[str, Any] = {}

        def job() -> None:
            try:
                box["value"] = fn()
            except Exception as err:  # handed back to the control thread below
                box["error"] = err
            finally:
                done.set()

        with self._lock:
            self._pending.append(job)
        if not done.wait(self._timeout):
            raise ValueError("the bridge window is busy; try again")
        if "error" in box:
            raise box["error"]
        result: T = box["value"]
        return result

    def status(self) -> dict[str, Any]:
        return self._invoke(self._host.remote_status)

    def start(self) -> None:
        self._invoke(self._host.remote_start)

    def stop(self) -> None:
        self._invoke(self._host.remote_stop)

    def set_option(self, name: str, value: str | float) -> None:
        self._invoke(lambda: self._host.remote_set(name, value))


def control_key(settings: Settings) -> tuple[bool, int, str, tuple[str, ...]] | None:
    """The settings that define the listener, or None when it should be off."""
    if not settings.control_enabled:
        return None
    try:
        allow = parse_allow(settings.control_allow)
    except ValueError:
        return None
    return (True, settings.control_port, settings.control_bind.strip(), allow)


class RemoteControl:
    """Starts, restarts, and stops the window's ``ControlServer`` to match Settings."""

    def __init__(
        self,
        remote: GuiRemote,
        *,
        log: Callable[[str, str], object],
        server_factory: Callable[..., ControlServer] = ControlServer,
    ) -> None:
        self._remote = remote
        self._log = log
        self._factory = server_factory
        self._key: tuple[bool, int, str, tuple[str, ...]] | None = None
        self.server: ControlServer | None = None
        self.status_text = "Off"
        self.error = ""

    def apply(self, settings: Settings, problems: dict[str, str]) -> None:
        """Match the listener to ``settings``; skipped while a control_* setting is invalid."""
        if any(key.startswith("control_") for key in problems):
            return
        key = control_key(settings)
        if key == self._key and (self.server is not None or key is None):
            return
        self.stop()
        self._key = key
        if key is None:
            self.status_text = "Off"
            return
        _, port, bind, allow = key
        try:
            self.server = self._factory(
                self._remote,
                port=port,
                bind=bind,
                allow=allow,
                log=lambda message: None,
            ).start()
        except (OSError, ValueError) as err:
            self.server = None
            self.error = f"Remote control could not listen on {bind}:{port}: {err}"
            self.status_text = self.error
            self._log("error", self.error)
            return
        self._remote.set_active(True)
        host, bound_port = self.server.address[:2]
        self.status_text = f"Listening on {host}:{bound_port}"
        self._log("info", f"Remote control: {self.status_text.lower()}")

    def stop(self) -> None:
        self.error = ""
        if self.server is not None:
            self.server.stop()
            self.server = None
            self._remote.set_active(False)
            self._log("info", "Remote control stopped")
        self.status_text = "Off"
