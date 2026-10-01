# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Named emulator scenarios for tests, the release regression, and demos."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from n1mm_scope_bridge.emulator.ft710 import Faults, Ft710Emulator, RadioState


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    configure: Callable[[Ft710Emulator], None]
    expect_error: str = ""
    """Start of the error the bridge must report, or empty if it streams normally."""


def _hook(fn: Callable[[Ft710Emulator, int], None]) -> Callable[[Ft710Emulator], None]:
    def configure(emu: Ft710Emulator) -> None:
        emu.on_frame = fn

    return configure


def _band_scan(emu: Ft710Emulator, i: int) -> None:
    emu.tune(14_000_000 + (i * 5_000) % 350_000)


def _span_steps(emu: Ft710Emulator, i: int) -> None:
    emu.set_span((i // 10) % 10)


def _mode_change(emu: Ft710Emulator, i: int) -> None:
    emu.set_scope_mode((0x04, 0x07, 0x0A)[(i // 20) % 3])  # Center, Cursor, Fixed


def _tx_burst(emu: Ft710Emulator, i: int) -> None:
    emu.set_tx(20 <= i % 60 < 40)


def _faults(**kw: object) -> Callable[[Ft710Emulator], None]:
    def configure(emu: Ft710Emulator) -> None:
        emu.faults = Faults(**kw)  # type: ignore[arg-type]

    return configure


SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in (
        Scenario("steady", "20 m FT8 segment, Center mode, nothing changes", lambda emu: None),
        Scenario("band-scan", "Tune 14.000 to 14.350 MHz in 5 kHz steps", _hook(_band_scan)),
        Scenario("span-steps", "Step through all 10 scope spans", _hook(_span_steps)),
        Scenario("mode-change", "Center, then Cursor, then Fixed scope mode", _hook(_mode_change)),
        Scenario("tx-burst", "Transmit for 20 of every 60 frames", _hook(_tx_burst)),
        Scenario("misaligned-start", "Stream starts mid-frame", _faults(start_offset=1234)),
        Scenario("corrupt-frames", "Every 25th frame loses sync", _faults(corrupt_every=25)),
        Scenario(
            "usb-unplug",
            "USB unplugged after 20 frames (1 s)",
            _faults(io_error_after_frames=20),
            expect_error="FT4222_SPIMaster_SingleRead failed",
        ),
        Scenario(
            "silent-radio",
            "Device opens but the scope sends nothing",
            _faults(silent=True),
            expect_error="No valid scope frames",
        ),
        Scenario(
            "not-connected",
            "Radio off or USB cable unplugged",
            _faults(open_status=2),
            expect_error="Could not open",
        ),
    )
}


def make_emulator(scenario: str = "steady", *, fps: float = 20.0, seed: int = 710) -> Ft710Emulator:
    """An emulator configured for ``scenario`` (see ``SCENARIOS``)."""
    try:
        chosen = SCENARIOS[scenario]
    except KeyError:
        raise KeyError(
            f"unknown scenario {scenario!r}; choose from: {', '.join(SCENARIOS)}"
        ) from None
    emu = Ft710Emulator(RadioState(), fps=fps, seed=seed)
    chosen.configure(emu)
    return emu
