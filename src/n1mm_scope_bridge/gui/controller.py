# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Runs the streaming pipeline for the GUI and reports through Qt signals.

Pipeline threads never call Qt (#207): their callbacks append to a locked
deque, and a ``QTimer`` on the GUI thread drains it every ``DRAIN_MS`` and
emits the signals there. (Emitting from a plain Python thread stalled the
sender on PySide6 6.12; see also ``remote.py``.) A second timer polls the
pipeline's health and statistics.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, QTimer, Signal

from n1mm_scope_bridge.bridge import build_pipeline
from n1mm_scope_bridge.n1mm import N1mmSender
from n1mm_scope_bridge.pipeline import Pipeline
from n1mm_scope_bridge.radios.base import ParsedFrame
from n1mm_scope_bridge.settings import Settings
from n1mm_scope_bridge.transport.ft4222 import Ft4222Error, Ft4222Reader, load_api

Source = tuple[Iterable[bytes], Callable[[], object]]
SourceFactory = Callable[[Settings], Source]
SenderFactory = Callable[[str, int], N1mmSender]
POLL_MS = 250
DRAIN_MS = 20
# Events held for the GUI thread; if it stalls this long, the oldest are dropped.
QUEUE_MAX = 256


def radio_source(settings: Settings) -> Source:
    """The real radio: LibFT4222 is loaded now; the device opens on the reader thread."""
    reader = Ft4222Reader(load_api(settings.ftdi_lib_dir or None), description=settings.device)
    return reader, reader.stop


def friendly_error(exc: BaseException) -> str:
    """One-line message for an operator (full details belong in the log)."""
    if isinstance(exc, Ft4222Error | ValueError | OSError):
        return str(exc)
    return f"Unexpected error: {type(exc).__name__}: {exc}"


class StreamController(QObject):
    started = Signal()
    stopped = Signal(str)  # "" when stopped normally, otherwise the error message
    status = Signal(object)  # ScopeStatus, from the sender thread (queued to the GUI)
    stats = Signal(object)  # PipelineStats, every POLL_MS while running
    warning = Signal(str)  # rate-limited bridge warnings (for the log)
    frame = Signal(object)  # ParsedFrame just sent to N1MM+, queued
    preview = Signal(object)  # ParsedFrame at the radio's rate (live display), queued

    def __init__(
        self,
        *,
        source_factory: SourceFactory = radio_source,
        sender_factory: SenderFactory = N1mmSender,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_factory = source_factory
        self._sender_factory = sender_factory
        self._pipe: Pipeline[ParsedFrame] | None = None
        self._sender: N1mmSender | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._lock = threading.Lock()
        self._queue: deque[tuple[str, object]] = deque(maxlen=QUEUE_MAX)
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(DRAIN_MS)
        self._drain_timer.timeout.connect(self._drain)
        # Read from the pipeline thread on every frame; a plain bool needs no lock.
        self.preview_enabled = False

    def _post(self, signal: str) -> Callable[[object], None]:
        """A callback for pipeline threads: queue the payload for ``signal``, no Qt."""

        def post(item: object) -> None:
            with self._lock:
                self._queue.append((signal, item))

        return post

    def _drain(self) -> None:
        """On the GUI thread: emit every queued event in order."""
        with self._lock:
            events = list(self._queue)
            self._queue.clear()
        for signal, item in events:
            getattr(self, signal).emit(item)

    def _emit_preview(self, item: ParsedFrame) -> None:
        """Forward a frame to the window only while the preview is shown (saves CPU)."""
        if self.preview_enabled:
            self._post("preview")(item)

    @property
    def running(self) -> bool:
        return self._pipe is not None

    def start(self, settings: Settings) -> bool:
        """Start streaming. Returns False (and emits ``stopped`` with why) on failure."""
        if self._pipe is not None:
            return True
        problems = settings.validate()
        if problems:
            self.stopped.emit("; ".join(f"{k}: {v}" for k, v in problems.items()))
            return False
        try:
            source, close = self._source_factory(settings)
            self._sender = self._sender_factory(settings.n1mm_host, settings.n1mm_port)
            self._pipe = build_pipeline(
                settings.to_bridge_config(),
                source,
                self._sender,
                close_source=close,
                on_status=self._post("status"),
                warn=self._post("warning"),
                on_frame=self._post("frame"),
                on_preview=self._emit_preview,
            )
            self._pipe.start()
        except Exception as exc:
            self._cleanup()
            self.stopped.emit(friendly_error(exc))
            return False
        self._drain_timer.start()
        self._timer.start()
        self.started.emit()
        return True

    def stop(self) -> None:
        """Stop streaming and wait for the pipeline threads (bounded)."""
        if self._pipe is None:
            return
        self._pipe.stop()
        error = self._finish()
        self.stopped.emit(error)

    def _poll(self) -> None:
        pipe = self._pipe
        if pipe is None:
            return
        self.stats.emit(pipe.stats())
        if not pipe.alive:
            self.stopped.emit(self._finish() or "Streaming stopped: the source ended.")

    def _finish(self) -> str:
        pipe = self._pipe
        message = ""
        if pipe is not None:
            try:
                pipe.join(timeout=5)
            except Exception as exc:
                message = friendly_error(exc)
        self._drain()  # the last status and warnings from the stopped threads
        self._cleanup()
        return message

    def _cleanup(self) -> None:
        self._timer.stop()
        self._drain_timer.stop()
        with self._lock:
            self._queue.clear()
        self._pipe = None
        if self._sender is not None:
            self._sender.close()
            self._sender = None
