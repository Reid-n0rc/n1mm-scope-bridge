# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The FT-710 emulator (#35), exercised through the real reader, parser, and pipeline."""

from __future__ import annotations

import pytest

from n1mm_scope_bridge.bridge import BridgeConfig, build_pipeline
from n1mm_scope_bridge.emulator import (
    SCENARIOS,
    Faults,
    Ft710Emulator,
    RadioState,
    Signal,
    make_emulator,
)
from n1mm_scope_bridge.emulator import ft710 as emu_mod
from n1mm_scope_bridge.radios import yaesu_scope as ys
from n1mm_scope_bridge.radios.ft710 import FT710
from n1mm_scope_bridge.transport.ft4222 import DeviceNotFound, Ft4222Error, Ft4222Reader


def read_parsed(emu: Ft710Emulator, n: int) -> list:  # type: ignore[type-arg]
    reader = Ft4222Reader(emu)
    out = []
    for raw in reader:
        out.append(FT710.parse(raw))
        if len(out) == n:
            reader.stop()
    return out


def test_steady_frames_parse_with_radio_state() -> None:
    emu = Ft710Emulator(RadioState(vfo_a_hz=7_074_000, span_index=6, scope_mode=0x04))
    frames = read_parsed(emu, 3)
    status = frames[-1].status
    assert (status.vfo_hz, status.span_hz, status.mode_family) == (7_074_000, 100_000, "center")
    assert frames[-1].spectrum.low_hz == 7_024_000
    assert emu.calls[:5] == ["open", "timeouts", "latency", "spi_init", "clock"]


def test_signals_appear_where_they_are_tuned() -> None:
    emu = Ft710Emulator(signals=(Signal(14_074_000, 200, 200, 1.0),), seed=1)
    spectrum = read_parsed(emu, 1)[0].spectrum
    centre = len(spectrum.levels) // 2
    assert max(spectrum.levels[centre - 3 : centre + 4]) >= 190
    assert max(spectrum.levels[:100]) < 60  # just noise away from the signal


def test_retuning_moves_signals() -> None:
    sig = (Signal(14_074_000, 200, 200, 1.0),)
    centred = Ft710Emulator(signals=sig).render_levels(0)
    shifted = Ft710Emulator(RadioState(vfo_a_hz=14_079_000), signals=sig).render_levels(0)
    assert centred.index(max(centred)) > shifted.index(max(shifted))


def test_operator_controls_change_frames() -> None:
    emu = Ft710Emulator()
    emu.tune(21_074_000)
    emu.set_span(9)
    emu.set_scope_mode(0x0A)
    emu.set_tx(True)
    parsed = read_parsed(emu, 1)[0]
    assert (parsed.status.vfo_hz, parsed.status.span_hz) == (21_074_000, 1_000_000)
    assert parsed.status.mode_family == "fixed"
    assert max(parsed.spectrum.levels) >= 220  # own transmit signal


def test_tx_status_bytes() -> None:
    emu = Ft710Emulator()
    emu.set_tx(True)
    reader = Ft4222Reader(emu)
    reader.open()
    raw = reader.read_frame()
    assert raw is not None
    assert raw[2900 + 22 : 2900 + 24] == bytes(emu_mod.TX_STATUS)


def test_set_span_validates() -> None:
    with pytest.raises(ValueError, match="span index"):
        Ft710Emulator().set_span(10)


def test_deterministic_with_seed() -> None:
    assert Ft710Emulator(seed=3).render_levels(5) == Ft710Emulator(seed=3).render_levels(5)


def test_pacing_uses_sleep() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(round(seconds, 6))
        now[0] += seconds

    emu = Ft710Emulator(fps=20, sleep=sleep, clock=lambda: now[0])
    read_parsed(emu, 2)
    assert sleeps[:2] == [0.05, 0.05]


def test_pacing_absorbs_generation_time() -> None:
    """Time spent building a frame counts toward the period, so the rate stays exact."""
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(round(seconds, 6))
        now[0] += seconds + 0.01  # each wake-up plus 10 ms of frame generation

    emu = Ft710Emulator(fps=20, sleep=sleep, clock=lambda: now[0])
    read_parsed(emu, 4)
    assert sleeps[1:4] == [0.04, 0.04, 0.04]


def test_pacing_does_not_burst_after_falling_behind() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(round(seconds, 6))
        now[0] += seconds + 0.2  # far slower than 20 frames/s

    emu = Ft710Emulator(fps=20, sleep=sleep, clock=lambda: now[0])
    read_parsed(emu, 3)
    assert all(s == 0.0 for s in sleeps[1:])


# --- faults ------------------------------------------------------------------------------


def test_wrong_description_and_busy_device() -> None:
    emu = Ft710Emulator()
    assert emu.open_ex("FT4222 B")[0] == emu_mod.FT_DEVICE_NOT_FOUND
    status, handle = emu.open_ex("FT4222 A")
    assert status == 0
    assert emu.open_ex("FT4222 A")[0] == emu_mod.FT_DEVICE_NOT_OPENED
    assert emu.spi_read(object(), 4)[0] == 1  # invalid handle
    emu.close(handle)
    assert emu.open_ex("FT4222 A")[0] == 0


@pytest.mark.parametrize("step", emu_mod.SETUP_STEPS)
def test_setup_failures(step: str) -> None:
    emu = Ft710Emulator(faults=Faults(setup_failure=step))
    with pytest.raises(Ft4222Error, match="FT_IO_ERROR"):
        Ft4222Reader(emu).open()


def test_not_connected() -> None:
    with pytest.raises(DeviceNotFound):
        Ft4222Reader(Ft710Emulator(faults=Faults(open_status=2))).open()


@pytest.mark.parametrize("padding", ["sync", "zero"])
@pytest.mark.parametrize("offset", [1, 1234, 3100, 4095])
def test_misaligned_start_resyncs(padding: str, offset: int) -> None:
    emu = Ft710Emulator(faults=Faults(start_offset=offset), padding=padding)  # type: ignore[arg-type]
    reader = Ft4222Reader(emu)
    frames = []
    for raw in reader:
        frames.append(raw)
        if len(frames) == 3:
            reader.stop()
    assert reader.resyncs >= 1
    parsed = [FT710.parse(f) for f in frames]
    assert all(p.status.vfo_hz == 14_074_000 for p in parsed)  # aligned, not shifted
    assert all(f[ys.DATA + ys.STATUS_SPAN] == 4 for f in frames)


def test_sync_padding_fills_unused_region() -> None:
    reader = Ft4222Reader(Ft710Emulator(padding="sync"))
    reader.open()
    raw = reader.read_frame()
    assert raw is not None
    repeats = (ys.FRAME_SIZE - ys.DATA - ys.DATA_LEN) // len(ys.SYNC)
    assert raw[-repeats * len(ys.SYNC) :] == ys.SYNC * repeats
    assert len(raw) == ys.FRAME_SIZE


# --- scenarios through the real pipeline ---------------------------------------------------


class Sink:
    def __init__(self) -> None:
        self.count = 0

    def send(self, payload: bytes) -> bool:
        self.count += 1
        return True


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_end_to_end(name: str) -> None:
    scenario = SCENARIOS[name]
    emu = make_emulator(name, fps=400)
    reader = Ft4222Reader(emu)
    sink = Sink()
    pipe = build_pipeline(
        BridgeConfig(FT710, "FT-710", rate_hz=10),
        reader,
        sink,
        close_source=reader.stop,
        warn=lambda m: None,
    )
    pipe.start()
    if scenario.expect_error:
        with pytest.raises(Ft4222Error, match=scenario.expect_error):
            pipe.join(timeout=10)
        return
    pipe.join(timeout=0.6)
    pipe.stop()
    pipe.join(timeout=5)
    assert sink.count >= 2, name
    assert pipe.stats().frames_read > 10


def test_scenarios_have_expected_effects() -> None:
    def statuses(name: str, n: int) -> list:  # type: ignore[type-arg]
        return [p.status for p in read_parsed(make_emulator(name, fps=0), n)]

    assert len({s.vfo_hz for s in statuses("band-scan", 5)}) == 5
    assert len({s.span_hz for s in statuses("span-steps", 21)}) == 3
    assert {s.mode_family for s in statuses("mode-change", 41)} == {"center", "cursor", "fixed"}


def test_unknown_scenario() -> None:
    with pytest.raises(KeyError, match="unknown scenario"):
        make_emulator("everything")
