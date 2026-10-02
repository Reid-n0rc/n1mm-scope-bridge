# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Radio emulators: run and test everything without a radio (docs/emulator.md)."""

from n1mm_scope_bridge.emulator.ft710 import Faults, Ft710Emulator, RadioState, Signal
from n1mm_scope_bridge.emulator.scenarios import SCENARIOS, Scenario, make_emulator

__all__ = [
    "SCENARIOS",
    "Faults",
    "Ft710Emulator",
    "RadioState",
    "Scenario",
    "Signal",
    "make_emulator",
]
