# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""hardware_smoke.py against the emulator (never a real radio)."""

from __future__ import annotations

from pathlib import Path

import dev_cat as dc
import hardware_smoke as hs
import pytest

from n1mm_scope_bridge.emulator import Faults, Ft710Emulator
from n1mm_scope_bridge.radios.base import ScopeStatus


def test_smoke_passes_on_the_emulator() -> None:
    emu = Ft710Emulator(fps=40)
    cat = dc.DevCat(dc.EmulatorCatPort(emu), sleep=lambda _: None)
    # Low rate + longer window: slow CI runners still meet the 80% packet floor.
    result = hs.run_smoke(emu, seconds=3.0, rate_hz=2, cat=cat, say=lambda _: None)
    assert result.passed, result.failures
    assert result.packets >= 4
    assert result.cat_checks >= 1
    assert result.probe.startswith("VFO 14074000 Hz")
    assert result.edges_khz is not None


def test_probe_failure_is_reported() -> None:
    result = hs.run_smoke(
        Ft710Emulator(faults=Faults(open_status=2)), seconds=1, say=lambda _: None
    )
    assert not result.passed
    assert "probe failed" in result.failures[0]


def test_stream_error_is_reported() -> None:
    emu = Ft710Emulator(fps=200, faults=Faults(io_error_after_frames=30))
    result = hs.run_smoke(emu, seconds=3, rate_hz=10, say=lambda _: None)
    assert any("error" in f for f in result.failures)


def test_evaluate_criteria() -> None:
    status = ScopeStatus(14_074_000, 20_000, "center", "Center (Normal)")
    good = hs.SmokeResult(seconds=10, frames_read=200, packets=40, edges_khz=(14064.0, 14084.0),
                          last_status=status)  # fmt: skip
    assert hs.evaluate(good, 4.0) == []
    bad = hs.SmokeResult(
        seconds=10, frames_read=100, packets=5, invalid_packets=1, bad_frames=5, resyncs=9,
        reinits=1, edges_khz=(7000.0, 7020.0), last_status=status, cat_mismatches=["x"],
        error="boom",
    )  # fmt: skip
    failures = hs.evaluate(bad, 4.0)
    assert len(failures) == 7


def test_report_and_main_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = tmp_path / "smoke.md"
    code = hs.main(["--dry-run", "--minutes", "0.03", "--rate", "10", "--report", str(report)])
    text = report.read_text(encoding="utf-8")
    assert "# FT-710 hardware smoke test" in text
    assert code == (0 if "**Result: PASS**" in text else 1)
    assert "emulator" in text
    capsys.readouterr()


def test_main_reports_missing_library(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = hs.main(
        ["--ftdi-lib-dir", str(tmp_path / "missing"), "--report", str(tmp_path / "r.md")]
    )
    assert code == 1
    assert "error:" in capsys.readouterr().out
