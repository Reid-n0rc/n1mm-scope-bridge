# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Replay the synthetic capture through the real CLI into an N1MM+ stand-in."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from regression_core import (
    MIN_PACKETS,
    ROOT,
    SPECTRUM_BINS,
    CheckFailed,
    Runner,
    Step,
    StepContext,
    drain,
    run_command,
    tail,
    udp_listener,
)

FIXTURE = ROOT / "tests" / "fixtures" / "ft710_synthetic.cap"


def check_packets(packets: list[bytes]) -> None:
    if len(packets) < MIN_PACKETS:
        raise CheckFailed(f"N1MM listener got {len(packets)} packets, expected >= {MIN_PACKETS}")
    for data in packets:
        try:
            root = ET.fromstring(data)
        except ET.ParseError as err:
            raise CheckFailed(f"invalid <Spectrum> XML: {err}") from None
        values = (root.findtext("SpectrumData") or "").split(",")
        if (
            root.tag != "Spectrum"
            or root.findtext("DataCount") != str(len(values))
            or len(values) != SPECTRUM_BINS
        ):
            raise CheckFailed("packet does not match the N1MM <Spectrum> format")


def e2e_replay(runner: Runner = run_command, fixture: Path = FIXTURE) -> None:
    with udp_listener() as rx:
        port = str(rx.getsockname()[1])
        cmd = ("uv", "run", "n1mm-scope-bridge", "run", "--replay", str(fixture), "--loop",
               "--duration", "2", "--rate", "10", "--port", port)  # fmt: skip
        code, out = runner(cmd)
        if code != 0:
            raise CheckFailed(f"bridge exited {code}:\n{tail(out)}")
        packets = drain(rx)
    check_packets(packets)


def steps(ctx: StepContext) -> list[Step]:
    return [Step("End-to-end replay to N1MM UDP listener", action=lambda: e2e_replay(ctx.runner))]
