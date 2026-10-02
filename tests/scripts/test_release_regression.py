# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import os
from pathlib import Path

import pytest
import release_regression as rr
from regression_core import GUI_SKIP, OUTPUT_TAIL
from stepload import fake_runner, load_step, ticking


def test_all_pass_in_order_with_timing() -> None:
    runner = fake_runner()
    results = rr.run_steps(
        [rr.Step("a", ("a",)), rr.Step("b", action=lambda: None)], runner=runner, clock=ticking()
    )
    assert [(r.name, r.status, r.seconds) for r in results] == [
        ("a", "PASS", 1.0),
        ("b", "PASS", 1.0),
    ]
    assert runner.calls == [("a",)]  # type: ignore[attr-defined]


def test_stops_after_first_failure() -> None:
    runner = fake_runner({"b": 3}, output="line\n" * 100)
    results = rr.run_steps(
        [rr.Step("a", ("a",)), rr.Step("b", ("b",)), rr.Step("c", ("c",))], runner=runner
    )
    assert [r.status for r in results] == ["PASS", "FAIL", "NOT RUN"]
    assert results[1].detail.startswith("exit code 3")
    assert results[1].detail.count("line") == OUTPUT_TAIL


def test_action_failure_is_reported() -> None:
    def boom() -> None:
        raise rr.CheckFailed("missing NOTICE")

    results = rr.run_steps(
        [rr.Step("check", action=boom), rr.Step("next", ("x",))], runner=fake_runner()
    )
    assert (results[0].status, results[0].detail) == ("FAIL", "missing NOTICE")
    assert results[1].status == "NOT RUN"


def test_disabled_and_windows_only_steps_are_skipped() -> None:
    steps = [
        rr.Step("later", disabled_reason="added by #4"),
        rr.Step("win", ("w",), windows_only=True),
    ]
    off_windows = rr.run_steps(steps, runner=fake_runner(), is_windows=False)
    assert [(r.status, r.detail) for r in off_windows] == [
        ("SKIPPED", "added by #4"),
        ("SKIPPED", "not running on Windows"),
    ]
    flagged = rr.run_steps(steps, runner=fake_runner(), is_windows=True, skip_windows_only=True)
    assert flagged[1].detail == "--skip-windows-only"
    on_windows = rr.run_steps(steps, runner=fake_runner(), is_windows=True)
    assert on_windows[1].status == "PASS"


def test_passed() -> None:
    ok, skip, fail = rr.Result("a", "PASS"), rr.Result("b", "SKIPPED"), rr.Result("c", "FAIL")
    assert rr.passed([ok], allow_skips=False)
    assert not rr.passed([ok, skip], allow_skips=False)
    assert rr.passed([ok, skip], allow_skips=True)
    assert not rr.passed([ok, fail], allow_skips=True)
    assert not rr.passed([rr.Result("d", "NOT RUN")], allow_skips=True)


def test_render_report() -> None:
    results = [
        rr.Result("lint", "PASS", 1.25),
        rr.Result("tests", "FAIL", 2, "boom", "uv run pytest"),
    ]
    report = rr.render_report(results, {"commit": "abc"}, ok=False)
    assert "**Result: FAIL**" in report
    assert "- commit: `abc`" in report
    assert "| 1 | lint | PASS | 1.2 |" in report
    assert "### tests (FAIL)" in report
    assert "`uv run pytest`" in report
    assert "boom" in report
    assert "## Details" not in rr.render_report(results[:1], {}, ok=True)


def test_default_steps_cover_the_release_checklist() -> None:
    steps = rr.default_steps(fake_runner())
    names = [s.name for s in steps]
    assert names[0] == "Locked clean environment"
    assert any("licensing" in n for n in names)
    assert any("hook" in n.lower() for n in names)
    assert "Installer silent install/run/uninstall" in {s.name for s in steps if s.windows_only}
    assert "GUI self-test" in names  # runs on every OS (Qt offscreen)
    pending = [s for s in steps if s.disabled_reason]
    assert all(s.disabled_reason.startswith("added by #") for s in pending)


def test_main_writes_report_and_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "r.md"
    ok = rr.main(
        ["--report", str(report)], steps=[rr.Step("a", ("a",))], meta={}, runner=fake_runner()
    )
    assert ok == 0
    assert "**Result: PASS**" in report.read_text(encoding="utf-8")
    bad = rr.main(
        ["--report", str(report)],
        steps=[rr.Step("a", ("a",))],
        meta={},
        runner=fake_runner({"a": 1}),
    )
    assert bad == 1
    capsys.readouterr()


def test_explicit_portable_run_passes_but_is_not_releasable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    steps = [
        rr.Step("win", ("w",), windows_only=True),
        rr.Step("later", disabled_reason="added by #6"),
    ]
    report = tmp_path / "r.md"
    code = rr.main(
        ["--report", str(report), "--skip-windows-only"], steps=steps, meta={}, runner=fake_runner()
    )
    assert code == 0
    assert "not releasable" in report.read_text(encoding="utf-8")
    assert "NOT RELEASABLE" in capsys.readouterr().err


def test_windows_steps_skipped_off_windows_without_flag_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    code = rr.main(
        ["--report", str(tmp_path / "r.md")],
        steps=[rr.Step("win", ("w",), windows_only=True)],
        meta={},
        runner=fake_runner(),
    )
    assert code == 1
    assert "NOT RELEASABLE" in capsys.readouterr().err


def test_environment_metadata() -> None:
    meta = rr.environment()
    assert set(meta) == {"commit", "ref", "platform", "python", "date (UTC)"}


def test_e2e_step_is_enabled() -> None:
    step = next(s for s in rr.default_steps(fake_runner()) if s.name.startswith("End-to-end"))
    assert step.action is not None
    assert not step.disabled_reason


def test_skip_gui_drops_gui_group_and_is_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    steps = rr.default_steps(fake_runner(), skip_gui=True)
    assert steps[0].command[-2:] == ("--no-group", "gui-dev")
    mypy = next(s for s in steps if s.name.startswith("Type check"))
    assert mypy.command[-2:] == ("--exclude", load_step("20_static_checks").GUI_PATHS)
    gui = next(s for s in steps if s.name == "GUI self-test")
    assert gui.disabled_reason == GUI_SKIP
    monkeypatch.delenv("UV_NO_GROUP", raising=False)
    code = rr.main(
        ["--report", str(tmp_path / "r.md"), "--skip-gui"],
        steps=[rr.Step("gui", disabled_reason=GUI_SKIP)],
        meta={},
        runner=fake_runner(),
    )
    assert code == 0
    assert os.environ["UV_NO_GROUP"] == "gui-dev"
    capsys.readouterr()


# --- step file discovery (#45) -------------------------------------------------------------


def test_step_files_load_in_filename_order(tmp_path: Path) -> None:
    for stem, name in (("20_second", "B"), ("10_first", "A"), ("99_last", "C")):
        (tmp_path / f"{stem}.py").write_text(
            "from regression_core import Step\n\n"
            f"def steps(ctx):\n    return [Step({name!r}, ('true',))]\n",
            encoding="utf-8",
        )
    (tmp_path / "helper.py").write_text(
        "raise AssertionError('not a step file')\n", encoding="utf-8"
    )
    assert [s.name for s in rr.default_steps(fake_runner(), directory=tmp_path)] == ["A", "B", "C"]


def test_step_file_without_steps_function_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "10_bad.py").write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"10_bad\.py has no steps"):
        rr.default_steps(fake_runner(), directory=tmp_path)


def test_every_shipped_step_file_is_well_formed() -> None:
    files = rr.load_step_files()
    assert [m.__name__.split(".")[-1][:2] for m in files] == sorted(
        m.__name__.split(".")[-1][:2] for m in files
    )
    assert len(files) >= 11
