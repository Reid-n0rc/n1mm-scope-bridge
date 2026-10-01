# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Run every FT-710 emulator scenario through the real CLI (no radio needed)."""

from __future__ import annotations

import json

from regression_core import (
    MIN_PACKETS,
    CheckFailed,
    Runner,
    Step,
    StepContext,
    drain,
    run_command,
    tail,
    udp_listener,
)

LIST_SCENARIOS = (
    "uv", "run", "python", "-c",
    "import json; from n1mm_scope_bridge.emulator import SCENARIOS; "
    "print(json.dumps({n: s.expect_error for n, s in SCENARIOS.items()}))",
)  # fmt: skip


def emulator_scenarios(runner: Runner = run_command) -> None:
    code, out = runner(LIST_SCENARIOS)
    if code != 0:
        raise CheckFailed(f"could not list emulator scenarios:\n{tail(out)}")
    scenarios: dict[str, str] = json.loads(out.strip().splitlines()[-1])
    if not scenarios:
        raise CheckFailed("no emulator scenarios defined")
    failures = []
    for name, expect_error in sorted(scenarios.items()):
        with udp_listener() as rx:
            cmd = ("uv", "run", "n1mm-scope-bridge", "run", "--scenario", name, "--duration", "2",
                   "--rate", "10", "--port", str(rx.getsockname()[1]))  # fmt: skip
            code, out = runner(cmd)
            packets = drain(rx)
        if expect_error:
            if code != 1 or expect_error not in out:
                failures.append(f"{name}: expected exit 1 with {expect_error!r}, got {code}")
        elif code != 0 or len(packets) < MIN_PACKETS:
            failures.append(f"{name}: exit {code}, {len(packets)} packets\n{tail(out, 5)}")
    if failures:
        raise CheckFailed("\n".join(failures))


def steps(ctx: StepContext) -> list[Step]:
    return [
        Step("Emulator scenarios through the CLI", action=lambda: emulator_scenarios(ctx.runner))
    ]
