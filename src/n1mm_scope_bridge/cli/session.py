# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""A restartable streaming session for ``run``, controllable over UDP (#30).

Implements ``control.BridgeController``: remote ``start``/``stop``/``set``
come in on the control thread while the main thread waits, so every
state change holds ``_lock``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from typing import Any, TextIO

from n1mm_scope_bridge.bridge import build_pipeline
from n1mm_scope_bridge.cat import ScopeModeKeeper
from n1mm_scope_bridge.cli.common import LatestStatus, format_status
from n1mm_scope_bridge.n1mm import N1mmSender
from n1mm_scope_bridge.pipeline import Pipeline
from n1mm_scope_bridge.radios.base import ParsedFrame, ScopeStatus
from n1mm_scope_bridge.settings import Settings

Source = tuple[Iterable[bytes], Callable[[], object]]
OPTION_FIELDS = {
    "name": "source_name",
    "rate": "rate_hz",
    "combine": "combine",
    "scaling": "scaling",
}


class StreamSession:
    def __init__(
        self,
        settings: Settings,
        make_source: Callable[[], Source],
        err: TextIO,
        *,
        keep_alive: bool = False,
        make_keeper: Callable[[Iterable[bytes]], ScopeModeKeeper | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._make_source = make_source
        self._err = err
        self._keep_alive = keep_alive
        self._clock = clock
        self._lock = threading.RLock()
        self._pipe: Pipeline[ParsedFrame] | None = None
        self._sender: N1mmSender | None = None
        self._latest = LatestStatus()
        self._make_keeper = make_keeper
        self._keeper: ScopeModeKeeper | None = None

    # -- BridgeController ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            pipe = self._pipe
            st = self._latest.value
            info: dict[str, Any] = {
                "streaming": pipe is not None and pipe.alive,
                "radio": self.settings.effective_name(),
                "n1mm": f"{self.settings.n1mm_host}:{self.settings.n1mm_port}",
                "rate": self.settings.rate_hz,
                "combine": self.settings.combine,
            }
            if st is not None:
                info.update(vfo_hz=st.vfo_hz, span_hz=st.span_hz, mode=st.mode_name)
            if pipe is not None:
                s = pipe.stats()
                info.update(
                    sent=s.emitted, read=s.frames_read, dropped=s.frames_dropped, bad=s.bad_frames
                )
            return info

    def start(self) -> None:
        with self._lock:
            if self._pipe is not None and self._pipe.alive:
                return
            self._finish()
            source, close = self._make_source()
            keeper = self._make_keeper(source) if self._make_keeper else None
            self._keeper = keeper
            self._sender = N1mmSender(self.settings.n1mm_host, self.settings.n1mm_port)

            def on_status(status: ScopeStatus) -> None:
                self._latest.update(status)
                if keeper is not None:
                    keeper.observe(status)

            self._pipe = build_pipeline(
                self.settings.to_bridge_config(),
                source,
                self._sender,
                close_source=close,
                on_status=on_status,
                warn=lambda m: print(f"warning: {m}", file=self._err),
            )
            self._pipe.start()

    def stop(self) -> None:
        with self._lock:
            self._finish()

    def set_option(self, name: str, value: str | float) -> None:
        field = OPTION_FIELDS.get(name)
        if field is None:
            raise ValueError(f"cannot set {name!r}")
        updated = self.settings.replace(**{field: value})
        problems = updated.validate()
        if problems:
            raise ValueError("; ".join(problems.values()))
        with self._lock:
            restart = self._pipe is not None and self._pipe.alive
            self.settings = updated
            if restart:  # rate and combine are fixed per pipeline, so restart it
                self._finish()
                self.start()

    # -- main thread --------------------------------------------------------------

    def wait(self, duration: float | None, interval: float = 1.0) -> None:
        """Report once per interval until done; Ctrl-C or ``duration`` ends it.

        Without ``keep_alive`` the session ends when the stream ends. With it
        (remote control on), it keeps running while stopped, waiting for
        ``start``. A stream error is re-raised after cleanup.
        """
        deadline = None if duration is None else self._clock() + duration
        try:
            while deadline is None or self._clock() < deadline:
                with self._lock:
                    pipe = self._pipe
                if pipe is not None and pipe.alive:
                    remaining = interval if deadline is None else max(0.0, deadline - self._clock())
                    pipe.join(timeout=min(interval, remaining))
                    print(format_status(self._latest.value, pipe), file=self._err)
                    continue
                if pipe is not None:
                    with self._lock:
                        self._finish()  # re-raises a stream error
                    if not self._keep_alive:
                        return
                elif not self._keep_alive:
                    return
                time.sleep(min(interval, 0.2))
        except KeyboardInterrupt:
            pass
        finally:
            with self._lock:
                self._finish()

    def _finish(self) -> None:
        """Stop the stream and restore the scope mode, even after a stream error.

        The keeper restores *before* the source closes, while the radio is
        still connected; a stream error is re-raised afterwards.
        """
        pipe, sender, keeper = self._pipe, self._sender, self._keeper
        self._pipe, self._sender, self._keeper = None, None, None
        try:
            if keeper is not None:
                keeper.restore()
            if pipe is not None:
                pipe.stop()
                pipe.join(timeout=5)
        finally:
            if sender is not None:
                sender.close()
