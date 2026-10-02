# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Threaded, multi-core streaming pipeline: reader -> process -> sender.

Each radio gets its own ``Pipeline`` with three non-daemon threads:

* **reader**: pulls raw frames from the transport. FT4222 reads are ctypes
  calls, which release the GIL, so USB I/O overlaps Python work even on
  standard CPython.
* **process**: parses frames and folds them into an ``Accumulator``.
* **sender**: on a fixed tick, takes the combined result and emits it.

Hand-offs never block the reader. ``LatestQueue`` drops the oldest frame when
full, because stale spectrum lines are worthless. Pipelines share no mutable
state, so on free-threaded Python (3.13t and later) the stages, and multiple
radios, run in parallel on separate cores. See docs/architecture.md.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar, cast

T = TypeVar("T")
R = TypeVar("R")


class Empty(Exception):
    """Raised by ``LatestQueue.get`` when nothing arrives before the timeout."""


class LatestQueue(Generic[T]):
    """Bounded, thread-safe FIFO that drops the oldest item instead of blocking."""

    def __init__(self, maxsize: int) -> None:
        if maxsize < 1:
            raise ValueError(f"maxsize must be >= 1, got {maxsize}")
        self._items: deque[T] = deque()
        self._maxsize = maxsize
        self._cond = threading.Condition()
        self._dropped = 0

    @property
    def dropped(self) -> int:
        with self._cond:
            return self._dropped

    def __len__(self) -> int:
        with self._cond:
            return len(self._items)

    def put(self, item: T) -> None:
        with self._cond:
            if len(self._items) >= self._maxsize:
                self._items.popleft()
                self._dropped += 1
            self._items.append(item)
            self._cond.notify()

    def get(self, timeout: float) -> T:
        with self._cond:
            if not self._cond.wait_for(lambda: bool(self._items), timeout):
                raise Empty
            return self._items.popleft()


class Accumulator(Protocol[R]):
    """Combines processed items between sender ticks. Must be thread-safe."""

    def add(self, item: R) -> None:
        """Fold one processed item into the pending result."""

    def take(self) -> R | None:
        """Return the combined item since the last take, or None if there is none."""


class LatestAccumulator(Generic[R]):
    """Keeps only the most recent item."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._item: R | None = None

    def add(self, item: R) -> None:
        with self._lock:
            self._item = item

    def take(self) -> R | None:
        with self._lock:
            item, self._item = self._item, None
            return item


@dataclass(frozen=True)
class PipelineStats:
    frames_read: int
    frames_dropped: int
    bad_frames: int
    emitted: int


_END = object()


class Pipeline(Generic[R]):
    """One radio's reader -> process -> sender threads.

    ``source`` yields raw frames until exhausted (replay) or closed (device).
    ``process`` turns a raw frame into an item, or raises one of
    ``skip_errors`` to have the frame counted as bad and skipped. ``emit``
    receives the accumulator's combined item once per ``1 / rate_hz`` seconds.
    Any other exception in any stage stops the pipeline and is re-raised by
    ``join()``.
    """

    def __init__(  # noqa: PLR0913 - stage callables plus keyword-only tuning options
        self,
        name: str,
        source: Iterable[bytes],
        process: Callable[[bytes], R],
        emit: Callable[[R], object],
        *,
        rate_hz: float = 4.0,
        accumulator: Accumulator[R] | None = None,
        close_source: Callable[[], object] | None = None,
        skip_errors: tuple[type[Exception], ...] = (ValueError,),
        queue_size: int = 8,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 < rate_hz <= 10:  # N1MM team: no more than 5-10 updates per second
            raise ValueError(f"rate_hz must be in (0, 10], got {rate_hz}")
        self.name = name
        self._source = source
        self._process = process
        self._emit = emit
        self._period = 1.0 / rate_hz
        self._acc: Accumulator[R] = accumulator or LatestAccumulator()
        self._close_source = close_source
        self._skip = skip_errors
        self._queue: LatestQueue[object] = LatestQueue(queue_size)
        self._clock = clock
        self._stop = threading.Event()
        self._processed_all = threading.Event()
        self._error_lock = threading.Lock()
        self._error: BaseException | None = None
        self._frames_read = 0
        self._bad_frames = 0
        self._emitted = 0
        self._threads = [
            threading.Thread(target=self._guard(fn), name=f"{name}-{stage}")
            for stage, fn in (
                ("reader", self._run_reader),
                ("process", self._run_process),
                ("sender", self._run_sender),
            )
        ]
        self._started = False

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        if self._started:
            raise RuntimeError("pipeline already started")
        self._started = True
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        """Ask every stage to finish. Safe to call from any thread, repeatedly."""
        if self._stop.is_set():
            return
        self._stop.set()
        if self._close_source is not None:
            self._close_source()  # unblocks a reader waiting on the device

    def join(self, timeout: float | None = None) -> bool:
        """Wait for all stages. Returns True when finished; re-raises a stage error."""
        deadline = None if timeout is None else time.monotonic() + timeout
        for thread in self._threads:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            thread.join(remaining)
        if self.error is not None:
            raise self.error
        return not self.alive

    @property
    def alive(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    @property
    def error(self) -> BaseException | None:
        with self._error_lock:
            return self._error

    def stats(self) -> PipelineStats:
        return PipelineStats(
            frames_read=self._frames_read,
            frames_dropped=self._queue.dropped,
            bad_frames=self._bad_frames,
            emitted=self._emitted,
        )

    # -- stages ------------------------------------------------------------------

    def _record(self, exc: BaseException) -> None:
        """Keep the first stage failure for join() and stop every stage."""
        with self._error_lock:
            if self._error is None:
                self._error = exc
        self.stop()

    def _guard(self, fn: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                fn()
            except Exception as exc:  # recorded, then re-raised by join()
                self._record(exc)
            except BaseException as exc:
                # SystemExit/KeyboardInterrupt in a stage: stop everything, keep it
                # for join(), and let it continue to propagate out of the thread.
                self._record(exc)
                raise

        return run

    def _run_reader(self) -> None:
        try:
            for raw in self._source:
                if self._stop.is_set():
                    return
                self._frames_read += 1
                self._queue.put(raw)
        finally:
            self._queue.put(_END)

    def _run_process(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    raw = self._queue.get(timeout=0.1)
                except Empty:
                    continue
                if raw is _END:
                    return
                try:
                    item = self._process(cast(bytes, raw))
                except self._skip:
                    self._bad_frames += 1
                    continue
                self._acc.add(item)
        finally:
            self._processed_all.set()

    def _run_sender(self) -> None:
        next_tick = self._clock() + self._period
        while True:
            finished = self._processed_all.is_set()
            if self._stop.wait(max(0.0, next_tick - self._clock())):
                return
            next_tick += self._period
            now = self._clock()
            if next_tick < now:  # fell behind (e.g. slow emit): skip missed ticks
                next_tick = now + self._period
            item = self._acc.take()
            if item is not None:
                self._emit(item)
                self._emitted += 1
            if finished:
                return


class MultiPipeline:
    """Runs one pipeline per radio and stops all of them if any one fails."""

    def __init__(self, pipelines: Sequence[Pipeline[Any]]) -> None:
        if not pipelines:
            raise ValueError("at least one pipeline is required")
        self.pipelines = list(pipelines)

    def start(self) -> None:
        for p in self.pipelines:
            p.start()

    def stop(self) -> None:
        for p in self.pipelines:
            p.stop()

    def join(self, poll: float = 0.1) -> None:
        """Wait until every pipeline finishes; on the first failure, stop the rest."""
        while any(p.alive for p in self.pipelines):
            if any(p.error is not None for p in self.pipelines):
                self.stop()
            time.sleep(poll)
        errors = [p.error for p in self.pipelines if p.error is not None]
        if errors:
            raise errors[0]
