# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Iterator

import pytest

from n1mm_scope_bridge.pipeline import (
    Empty,
    LatestAccumulator,
    LatestQueue,
    MultiPipeline,
    Pipeline,
)

FAST = 10.0  # Hz, the maximum allowed rate, keeps tests quick


def as_int(raw: bytes) -> int:
    return int.from_bytes(raw, "big")


def frames(n: int) -> list[bytes]:
    return [i.to_bytes(2, "big") for i in range(1, n + 1)]


class Device:
    """Endless source that only stops when closed, like the FT4222 reader."""

    def __init__(self) -> None:
        self.closed = threading.Event()
        self.close_calls = 0

    def __iter__(self) -> Iterator[bytes]:
        while not self.closed.is_set():
            self.closed.wait(0.002)
            yield b"\x01"

    def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


def no_leaked_threads(name: str) -> bool:
    return not [t for t in threading.enumerate() if t.name.startswith(f"{name}-")]


# --- LatestQueue -----------------------------------------------------------------


def test_queue_is_fifo() -> None:
    q: LatestQueue[int] = LatestQueue(3)
    for i in range(3):
        q.put(i)
    assert len(q) == 3
    assert [q.get(0) for _ in range(3)] == [0, 1, 2]


def test_queue_drops_oldest_when_full() -> None:
    q: LatestQueue[int] = LatestQueue(2)
    for i in range(5):
        q.put(i)
    assert q.dropped == 3
    assert [q.get(0), q.get(0)] == [3, 4]


def test_queue_get_times_out() -> None:
    q: LatestQueue[int] = LatestQueue(1)
    start = time.monotonic()
    with pytest.raises(Empty):
        q.get(0.05)
    assert time.monotonic() - start >= 0.04


def test_queue_get_wakes_on_put_from_other_thread() -> None:
    q: LatestQueue[int] = LatestQueue(1)
    threading.Timer(0.02, q.put, args=(7,)).start()
    assert q.get(2.0) == 7


@pytest.mark.parametrize("size", [0, -1])
def test_queue_rejects_bad_size(size: int) -> None:
    with pytest.raises(ValueError, match="maxsize"):
        LatestQueue(size)


def test_latest_accumulator() -> None:
    acc: LatestAccumulator[int] = LatestAccumulator()
    assert acc.take() is None
    acc.add(1)
    acc.add(2)
    assert acc.take() == 2
    assert acc.take() is None


# --- Pipeline ----------------------------------------------------------------------


def test_replay_runs_to_completion_and_flushes_last_item() -> None:
    out: list[int] = []
    p = Pipeline("replay", frames(5), as_int, out.append, rate_hz=FAST)
    p.start()
    assert p.join(timeout=5) is True
    assert out[-1] == 5
    stats = p.stats()
    assert (stats.frames_read, stats.bad_frames, stats.emitted) == (5, 0, len(out))
    assert no_leaked_threads("replay")


def test_bad_frames_are_skipped_and_counted() -> None:
    def process(raw: bytes) -> int:
        value = as_int(raw)
        if value % 2 == 0:
            raise ValueError("bad frame")
        return value

    out: list[int] = []
    p = Pipeline("bad", frames(6), process, out.append, rate_hz=FAST, queue_size=16)
    p.start()
    p.join(timeout=5)
    assert p.stats().bad_frames == 3
    assert out[-1] == 5


def test_reader_is_not_blocked_by_a_slow_sender() -> None:
    release = threading.Event()
    emitting = threading.Event()
    out: list[int] = []

    def slow_emit(item: int) -> None:
        emitting.set()
        release.wait(5)
        out.append(item)

    gate = threading.Event()

    def source() -> Iterator[bytes]:
        yield b"\x00\x01"
        gate.wait(5)  # hold the rest until the sender is stuck in emit
        yield from frames(1000)

    p = Pipeline("slow", source(), as_int, slow_emit, rate_hz=FAST, queue_size=4)
    p.start()
    assert emitting.wait(5)
    gate.set()
    deadline = time.monotonic() + 5
    while p.stats().frames_read < 1001 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert p.stats().frames_read == 1001  # reader finished while emit was blocked
    release.set()
    p.join(timeout=5)
    assert out[-1] == 1000


def test_slow_emit_skips_missed_ticks() -> None:
    calls: list[float] = []

    def emit(item: int) -> None:
        calls.append(time.monotonic())
        if len(calls) == 1:
            time.sleep(0.35)  # miss several 0.1 s ticks

    p = Pipeline("late", Device(), as_int, emit, rate_hz=FAST)
    p.start()
    time.sleep(0.6)
    p.stop()
    p.join(timeout=2)
    # Missed ticks are dropped, not replayed back to back.
    assert all(b - a > 0.05 for a, b in itertools.pairwise(calls[1:]))


@pytest.mark.parametrize("stage", ["source", "process", "emit"])
def test_stage_error_stops_pipeline_and_is_reraised(stage: str) -> None:
    device = Device()
    boom = RuntimeError(f"{stage} failed")

    def source() -> Iterator[bytes]:
        yield from device
        if stage == "source":
            raise boom

    def process(raw: bytes) -> int:
        if stage == "process":
            raise boom
        return 1

    def emit(item: int) -> None:
        if stage == "emit":
            raise boom

    def failing_source() -> Iterator[bytes]:
        yield b"\x01"
        raise boom

    p = Pipeline(
        f"err-{stage}",
        failing_source() if stage == "source" else source(),
        process,
        emit,
        rate_hz=FAST,
        close_source=device.close,
    )
    p.start()
    with pytest.raises(RuntimeError, match=f"{stage} failed"):
        p.join(timeout=5)
    assert p.error is boom
    assert not p.alive
    assert no_leaked_threads(f"err-{stage}")


def test_stop_is_fast_idempotent_and_closes_source_once() -> None:
    device = Device()
    p = Pipeline("dev", device, as_int, lambda _: None, rate_hz=FAST, close_source=device.close)
    p.start()
    time.sleep(0.05)
    start = time.monotonic()
    p.stop()
    p.stop()
    assert p.join(timeout=1) is True
    assert time.monotonic() - start < 1.0
    assert device.close_calls == 1
    assert no_leaked_threads("dev")


def test_join_timeout_returns_false_while_running() -> None:
    device = Device()
    p = Pipeline("busy", device, as_int, lambda _: None, rate_hz=FAST, close_source=device.close)
    p.start()
    assert p.join(timeout=0.05) is False
    p.stop()
    assert p.join(timeout=2) is True


def test_start_twice_rejected() -> None:
    p = Pipeline("twice", [], as_int, lambda _: None, rate_hz=FAST)
    p.start()
    with pytest.raises(RuntimeError, match="already started"):
        p.start()
    p.join(timeout=2)


@pytest.mark.parametrize("rate", [0, -1, 10.5])
def test_rate_is_validated(rate: float) -> None:
    with pytest.raises(ValueError, match="rate_hz"):
        Pipeline("rate", [], as_int, lambda _: None, rate_hz=rate)


# --- MultiPipeline -----------------------------------------------------------------


def test_multi_pipeline_runs_radios_independently() -> None:
    out_a: list[int] = []
    out_b: list[int] = []
    multi = MultiPipeline(
        [
            Pipeline("radio-a", frames(3), as_int, out_a.append, rate_hz=FAST),
            Pipeline("radio-b", frames(7), as_int, out_b.append, rate_hz=FAST),
        ]
    )
    multi.start()
    multi.join(poll=0.01)
    assert (out_a[-1], out_b[-1]) == (3, 7)


def test_multi_pipeline_failure_stops_the_others() -> None:
    device = Device()

    def bad(_: bytes) -> int:
        raise RuntimeError("radio-b exploded")

    multi = MultiPipeline(
        [
            Pipeline("ok", device, as_int, lambda _: None, rate_hz=FAST, close_source=device.close),
            Pipeline("broken", frames(1), bad, lambda _: None, rate_hz=FAST),
        ]
    )
    multi.start()
    with pytest.raises(RuntimeError, match="exploded"):
        multi.join(poll=0.01)
    assert device.close_calls == 1
    assert no_leaked_threads("ok")


def test_multi_pipeline_stop() -> None:
    device = Device()
    multi = MultiPipeline(
        [Pipeline("m", device, as_int, lambda _: None, rate_hz=FAST, close_source=device.close)]
    )
    multi.start()
    multi.stop()
    multi.join(poll=0.01)
    assert device.close_calls == 1


def test_multi_pipeline_requires_pipelines() -> None:
    with pytest.raises(ValueError, match="at least one"):
        MultiPipeline([])


def test_process_stage_waits_through_idle_periods() -> None:
    """The process thread keeps polling while the source is quiet (Empty path)."""
    resume = threading.Event()

    def quiet_source() -> Iterator[bytes]:
        resume.wait(5)  # longer than the process stage's 0.1 s poll
        yield b"\x00\x09"

    out: list[int] = []
    p = Pipeline("idle", quiet_source(), as_int, out.append, rate_hz=FAST)
    p.start()
    time.sleep(0.3)
    assert p.alive
    resume.set()
    p.join(timeout=5)
    assert out == [9]
