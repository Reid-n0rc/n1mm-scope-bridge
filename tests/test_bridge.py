# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import socket
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from frames import make_ft4222_frame

from n1mm_scope_bridge.bridge import (
    BridgeConfig,
    RateLimiter,
    SpectrumCombiner,
    build_pipeline,
)
from n1mm_scope_bridge.n1mm import N1mmSender
from n1mm_scope_bridge.radios.base import ParsedFrame, ScopeStatus
from n1mm_scope_bridge.radios.ft710 import FT710
from n1mm_scope_bridge.spectrum import SpectrumFrame
from n1mm_scope_bridge.transport.replay import CaptureReader

FIXTURE = Path(__file__).parent / "fixtures" / "ft710_synthetic.cap"
STATUS = ScopeStatus(14_074_000, 100_000, "center", "Center (Normal)")


def item(levels: tuple[int, ...], low: int = 1000, status: ScopeStatus = STATUS) -> ParsedFrame:
    return ParsedFrame(SpectrumFrame(low, low + 100, levels, 255), status)


# --- combiner ------------------------------------------------------------------


def test_latest_keeps_last() -> None:
    c = SpectrumCombiner("latest")
    assert c.take() is None
    c.add(item((1, 2)))
    c.add(item((5, 6)))
    taken = c.take()
    assert taken is not None
    assert taken.spectrum.levels == (5, 6)
    assert c.take() is None


def test_average_rounds_mean() -> None:
    c = SpectrumCombiner("average")
    for levels in [(0, 10), (1, 20), (2, 31)]:
        c.add(item(levels))
    taken = c.take()
    assert taken is not None
    assert taken.spectrum.levels == (1, 20)


def test_peak_holds_max() -> None:
    c = SpectrumCombiner("peak")
    for levels in [(0, 99), (50, 1), (3, 4)]:
        c.add(item(levels))
    taken = c.take()
    assert taken is not None
    assert taken.spectrum.levels == (50, 99)


@pytest.mark.parametrize("mode", ["average", "peak"])
def test_retune_restarts_combination(mode: str) -> None:
    c = SpectrumCombiner(mode)  # type: ignore[arg-type]
    c.add(item((200, 200)))
    later = ScopeStatus(7_074_000, 100_000, "center", "Center (Normal)")
    c.add(item((10, 20), low=5000, status=later))
    taken = c.take()
    assert taken is not None
    assert taken.spectrum.levels == (10, 20)
    assert taken.status is later


def test_combiner_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="combine"):
        SpectrumCombiner("median")  # type: ignore[arg-type]


def test_rate_limiter() -> None:
    now = [0.0]
    limiter = RateLimiter(1.0, clock=lambda: now[0])
    assert limiter.allow()
    assert not limiter.allow()
    now[0] = 0.99
    assert not limiter.allow()
    now[0] = 1.0
    assert limiter.allow()


# --- config ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"name": ""}, "name"),
        ({"scaling": 0.0}, "scaling"),
        ({"rate_hz": 11.0}, "rate"),
        ({"rate_hz": 0.0}, "rate"),
        ({"combine": "median"}, "combine"),
    ],
)
def test_config_validation(kw: dict[str, object], message: str) -> None:
    args: dict[str, object] = {"profile": FT710, "name": "FT-710"}
    args.update(kw)
    with pytest.raises(ValueError, match=message):
        BridgeConfig(**args)  # type: ignore[arg-type]


# --- pipeline -----------------------------------------------------------------------


class FakeSender:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def send(self, payload: bytes) -> bool:
        self.payloads.append(payload)
        return True


def run(frames: list[bytes]) -> tuple[FakeSender, list[str], list[ScopeStatus]]:
    sender = FakeSender()
    warnings: list[str] = []
    statuses: list[ScopeStatus] = []
    config = BridgeConfig(FT710, "FT-710", rate_hz=10)
    pipe = build_pipeline(config, frames, sender, warn=warnings.append, on_status=statuses.append)
    pipe.start()
    pipe.join(timeout=5)
    return sender, warnings, statuses


def test_pipeline_sends_n1mm_packets() -> None:
    sender, warnings, statuses = run([make_ft4222_frame()])
    assert len(sender.payloads) >= 1
    root = ET.fromstring(sender.payloads[-1])
    assert root.findtext("Name") == "FT-710"
    assert root.findtext("LowScopeFrequency") == "14024"
    assert root.findtext("DataCount") == "850"
    assert warnings == []
    assert statuses[-1].vfo_hz == 14_074_000


def test_pipeline_skips_bad_frames() -> None:
    sender, _, _ = run([b"short", make_ft4222_frame()])
    assert len(sender.payloads) >= 1


def test_non_center_mode_warns_once_per_second() -> None:
    frames = [make_ft4222_frame(scope_mode=0x07)]
    _, warnings, _ = run(frames)
    assert len(warnings) == 1
    assert "Cursor (Normal)" in warnings[0]
    assert "Center" in warnings[0]


def test_replay_fixture_end_to_end_over_udp() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(5)
        port = rx.getsockname()[1]
        reader = CaptureReader(FIXTURE, fps=50)
        sender = N1mmSender("127.0.0.1", port)
        pipe = build_pipeline(
            BridgeConfig(FT710, "FT-710", rate_hz=10, combine="peak"),
            reader,
            sender,
            close_source=reader.stop,
        )
        pipe.start()
        data, _ = rx.recvfrom(65535)
        pipe.join(timeout=5)
        sender.close()
    root = ET.fromstring(data)
    assert root.tag == "Spectrum"
    levels = [int(v) for v in (root.findtext("SpectrumData") or "").split(",")]
    assert len(levels) == 850
    assert max(levels) > 60
    assert not [t for t in threading.enumerate() if t.name.startswith("ft710-")]


def test_on_frame_receives_exactly_what_was_sent() -> None:
    sender = FakeSender()
    seen: list[ParsedFrame] = []
    pipe = build_pipeline(
        BridgeConfig(FT710, "FT-710", rate_hz=10),
        [make_ft4222_frame()],
        sender,
        on_frame=seen.append,
        warn=lambda _m: None,
    )
    pipe.start()
    pipe.join(timeout=5)
    assert len(seen) == len(sender.payloads) >= 1
    root = ET.fromstring(sender.payloads[-1])
    assert root.findtext("DataCount") == str(len(seen[-1].spectrum.levels))
