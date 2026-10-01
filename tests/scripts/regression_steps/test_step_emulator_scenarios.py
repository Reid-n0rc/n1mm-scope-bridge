# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import socket
from collections.abc import Sequence

import pytest
from regression_core import CheckFailed, Runner
from stepload import SPECTRUM, fake_runner, load_step

emu = load_step("65_emulator_scenarios")


def scenario_runner(listing: str, results: dict[str, tuple[int, str, int]]) -> Runner:
    """Fake CLI: listing for LIST_SCENARIOS, else (exit, output, packets) per scenario."""

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        if tuple(cmd) == emu.LIST_SCENARIOS:
            return 0, listing
        name = cmd[cmd.index("--scenario") + 1]
        code, out, packets = results[name]
        port = int(cmd[cmd.index("--port") + 1])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
            for _ in range(packets):
                tx.sendto(SPECTRUM, ("127.0.0.1", port))
        return code, out

    return run


def test_emulator_scenarios_pass() -> None:
    listing = '{"steady": "", "usb-unplug": "SingleRead failed"}'
    emu.emulator_scenarios(
        scenario_runner(
            listing, {"steady": (0, "", 6), "usb-unplug": (1, "error: SingleRead failed", 0)}
        )
    )


@pytest.mark.parametrize(
    ("results", "message"),
    [
        (
            {"steady": (0, "", 1), "usb-unplug": (1, "SingleRead failed", 0)},
            "steady: exit 0, 1 packets",
        ),
        ({"steady": (0, "", 6), "usb-unplug": (0, "", 6)}, "usb-unplug: expected exit 1"),
    ],
)
def test_emulator_scenario_failures(results: dict[str, tuple[int, str, int]], message: str) -> None:
    listing = '{"steady": "", "usb-unplug": "SingleRead failed"}'
    with pytest.raises(CheckFailed, match=message):
        emu.emulator_scenarios(scenario_runner(listing, results))


def test_emulator_scenarios_listing_errors() -> None:
    with pytest.raises(CheckFailed, match="could not list"):
        emu.emulator_scenarios(fake_runner({"uv": 1}))
    with pytest.raises(CheckFailed, match="no emulator scenarios"):
        emu.emulator_scenarios(scenario_runner("{}", {}))
