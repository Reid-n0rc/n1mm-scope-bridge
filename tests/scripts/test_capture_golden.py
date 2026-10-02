# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import capture_golden as cg
import dev_cat as dc
import pytest

from n1mm_scope_bridge.emulator import Faults, Ft710Emulator
from n1mm_scope_bridge.transport.ft4222 import LibraryNotFound


def test_checklist_covers_the_issue() -> None:
    names = [c.name for c in cg.CASES]
    assert [n for n in names if n.startswith("center-span-")] == [
        f"center-span-{i}" for i in range(10)
    ]
    for name in ("cursor-mode", "fixed-mode", "tx-dummy-load", "power-on-startup", "usb-replug"):
        assert name in names
    tx = next(c for c in cg.CASES if c.name == "tx-dummy-load")
    assert "DUMMY LOAD" in tx.instructions
    assert "never transmits" in tx.instructions


def test_git_blob_hash_matches_git() -> None:
    expected = subprocess.run(
        ["git", "hash-object", str(cg.PARSER_FILE)], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert cg.git_blob_hash(cg.PARSER_FILE) == expected


def test_dry_run_session_writes_fixtures_and_manifest(tmp_path: Path) -> None:
    said: list[str] = []
    cases = [c for c in cg.CASES if c.name in ("center-span-4", "power-on-startup")]
    manifest = cg.run_session(
        cg._emulator_for,
        tmp_path,
        ask=lambda _: "y",
        say=said.append,
        auto_yes=True,
        dry_run=True,
        cases=cases,
        seconds=0.2,
    )
    assert manifest["dry_run"] is True
    assert manifest["validated_against"] == cg.git_blob_hash(cg.PARSER_FILE)
    first = manifest["cases"][0]
    assert first["confirmed"] is True
    assert first["decoded"]["span_hz"] == 20_000
    assert (tmp_path / "center-span-4.raw").stat().st_size <= cg.MAX_FIXTURE_BYTES
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8")) == manifest
    assert any("Decoded: VFO 14.074000 MHz" in s for s in said)


def test_interactive_answers_skip_and_notes(tmp_path: Path) -> None:
    answers = iter(["FW 1.23", "", "no, span was 50 kHz", "s"])
    cases = [c for c in cg.CASES if c.name in ("center-span-4", "cursor-mode")]
    manifest = cg.run_session(
        cg._emulator_for,
        tmp_path,
        ask=lambda _: next(answers),
        say=lambda _: None,
        auto_yes=False,
        dry_run=False,
        cases=cases,
        seconds=0.2,
    )
    assert manifest["firmware"] == "FW 1.23"
    assert manifest["cases"][0]["confirmed"] is False
    assert manifest["cases"][0]["operator_note"] == "no, span was 50 kHz"
    assert manifest["cases"][1] == {"name": "cursor-mode", "skipped": True}


def test_recording_error_is_noted(tmp_path: Path) -> None:
    def broken(_: cg.Case) -> Ft710Emulator:
        return Ft710Emulator(faults=Faults(open_status=2))

    said: list[str] = []
    manifest = cg.run_session(
        broken,
        tmp_path,
        ask=lambda _: "y",
        say=said.append,
        auto_yes=True,
        dry_run=True,
        cases=cg.CASES[:1],
    )
    assert "Could not open" in manifest["cases"][0]["error"]
    assert any("Could not record" in s for s in said)


def test_decode_of_capture_without_frames(tmp_path: Path) -> None:
    path = tmp_path / "empty.raw"
    path.write_bytes(b"N1MMSB1-RAW FT-710 4096\n")
    assert cg.decode(path) == {"frames": 0, "span_unavailable_frames": 0}


def test_main_dry_run_never_writes_to_the_fixture_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert cg.main(["--dry-run", "--yes", "--only", "center-span-0", "--seconds", "0.2"]) == 0
    assert (tmp_path / "golden-dry-run" / "manifest.json").exists()
    assert "Wrote 1 cases" in capsys.readouterr().out


def test_main_unknown_case(capsys: pytest.CaptureFixture[str]) -> None:
    assert cg.main(["--dry-run", "--only", "nope"]) == 1
    assert "no cases match" in capsys.readouterr().out


def test_main_reports_missing_ftdi_library(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def missing(lib_dir: str | None) -> None:
        raise LibraryNotFound("Could not load FTDI's LibFT4222/D2XX libraries")

    monkeypatch.setattr(cg, "load_api", missing)
    assert cg.main(["--ftdi-lib-dir", "/nowhere"]) == 1
    assert "error: Could not load FTDI" in capsys.readouterr().out


def test_main_real_radio_path_uses_one_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    emu = Ft710Emulator()
    monkeypatch.setattr(cg, "load_api", lambda lib_dir: emu)
    answers = iter(["FW", "", "y"])
    code = cg.main(
        ["--out", str(tmp_path), "--only", "center-span-4", "--seconds", "0.2"],
        ask=lambda _: next(answers),
    )
    assert code == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dry_run"] is False
    assert manifest["cases"][0]["confirmed"] is True


# --- unattended (--auto) mode --------------------------------------------------------


def test_cases_know_their_auto_settings() -> None:
    by_name = {c.name: c for c in cg.CASES}
    assert (by_name["center-span-9"].auto_span, by_name["center-span-9"].auto_mode) == (9, "4")
    assert by_name["cursor-mode"].auto_mode == "7"
    assert by_name["fixed-mode"].auto_mode == "A"
    operator = {c.name for c in cg.CASES if c.operator_only}
    assert operator == {"tx-dummy-load", "power-on-startup", "usb-replug"}


def test_auto_session_sets_confirms_and_restores(tmp_path: Path) -> None:
    emu = Ft710Emulator()
    emu.set_span(3)
    emu.set_scope_mode(0x07)  # the operator's own setting: Cursor, 10 kHz
    port = dc.EmulatorCatPort(emu)
    cat = dc.DevCat(port, sleep=lambda _: None)
    cases = [c for c in cg.CASES if c.name in ("center-span-0", "fixed-mode", "usb-replug")]
    manifest = cg.run_session(
        cg._iter_same(emu), tmp_path, ask=lambda _: "", say=lambda _: None, auto_yes=True,
        dry_run=True, cases=cases, seconds=0.3, cat=cat, firmware="test", settle=lambda: None,
    )  # fmt: skip
    results = {c["name"]: c for c in manifest["cases"]}
    assert manifest["mode"] == "auto"
    assert manifest["original_scope"] == {"span_index": 3, "mode": "7"}
    assert results["center-span-0"]["confirmed"] is True
    assert results["center-span-0"]["confirmed_by"] == "cat+scope-stream"
    assert results["fixed-mode"]["confirmed"] is True
    assert results["usb-replug"] == {
        "name": "usb-replug",
        "skipped": True,
        "reason": "operator-only",
    }
    assert (emu.state.span_index, emu.state.scope_mode) == (3, 0x07)  # restored
    sets = [w for w in port.writes if len(w) > 5]
    assert all(dc.SET_PATTERN.match(w) for w in sets)  # only span/mode sets were sent


def test_auto_main_dry_run_and_argument_checks(tmp_path: Path) -> None:
    assert cg.main(["--auto"]) == 1  # needs --cat-port unless --dry-run
    out = tmp_path / "auto"
    assert cg.main(["--auto", "--dry-run", "--out", str(out), "--only", "center-span-4",
                    "--seconds", "0.3"]) == 0  # fmt: skip
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cases"][0]["confirmed"] is True
