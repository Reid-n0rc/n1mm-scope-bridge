# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import io
import itertools
import os
import socket
import tarfile
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
import release_regression as rr

LIC = ".dist-info/licenses/"


def fake_runner(codes: dict[str, int] | None = None, output: str = "out") -> rr.Runner:
    calls: list[tuple[str, ...]] = []

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        calls.append(tuple(cmd))
        return (codes or {}).get(cmd[0], 0), output

    run.calls = calls  # type: ignore[attr-defined]
    return run


def ticking() -> Callable[[], float]:
    counter = itertools.count()
    return lambda: float(next(counter))


# --- run_steps ------------------------------------------------------------------


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
    assert results[1].detail.count("line") == rr.OUTPUT_TAIL


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


# --- archive checks ---------------------------------------------------------------


def make_wheel(path: Path, extra: Sequence[str] = (), drop: str = "") -> Path:
    names = ["n1mm_scope_bridge/__init__.py"] + [f"pkg-0.1{LIC}{n}" for n in rr.LICENSE_FILES]
    with zipfile.ZipFile(path, "w") as zf:
        for name in [n for n in names if not (drop and n.endswith(drop))] + list(extra):
            zf.writestr(name, "x")
    return path


def make_sdist(path: Path, extra: Sequence[str] = (), drop: str = "") -> Path:
    names = [*rr.LICENSE_FILES, "pyproject.toml", "src/n1mm_scope_bridge/__init__.py", "tests/t.py"]
    with tarfile.open(path, "w:gz") as tf:
        for name in [n for n in names if n != drop] + list(extra):
            info = tarfile.TarInfo(f"pkg-0.1/{name}")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
    return path


def test_good_archives_pass(tmp_path: Path) -> None:
    make_wheel(tmp_path / "p.whl")
    make_sdist(tmp_path / "p.tar.gz")
    rr.check_dists(tmp_path)


@pytest.mark.parametrize("lic", rr.LICENSE_FILES)
def test_wheel_missing_license(tmp_path: Path, lic: str) -> None:
    with pytest.raises(rr.CheckFailed, match=f"licenses/{lic}"):
        rr.check_wheel(make_wheel(tmp_path / "p.whl", drop=lic))


def test_wheel_without_package(tmp_path: Path) -> None:
    with pytest.raises(rr.CheckFailed, match="does not contain the package"):
        rr.check_wheel(make_wheel(tmp_path / "p.whl", drop="__init__.py"))


@pytest.mark.parametrize("binary", ["lib/LibFT4222-64.dll", "x/ftd2xx.dll", "libft4222.so.1.4"])
def test_archives_reject_ftdi_binaries(tmp_path: Path, binary: str) -> None:
    with pytest.raises(rr.CheckFailed, match="FTDI"):
        rr.check_wheel(make_wheel(tmp_path / "p.whl", extra=[binary]))
    with pytest.raises(rr.CheckFailed, match="FTDI"):
        rr.check_sdist(make_sdist(tmp_path / "p.tar.gz", extra=[binary]))


@pytest.mark.parametrize(
    ("drop", "message"),
    [
        ("NOTICE", "missing NOTICE"),
        ("pyproject.toml", "missing pyproject"),
        ("tests/t.py", "no tests/"),
    ],
)
def test_sdist_requirements(tmp_path: Path, drop: str, message: str) -> None:
    with pytest.raises(rr.CheckFailed, match=message):
        rr.check_sdist(make_sdist(tmp_path / "p.tar.gz", drop=drop))


def test_check_dists_needs_exactly_one_of_each(tmp_path: Path) -> None:
    with pytest.raises(rr.CheckFailed, match="expected one wheel"):
        rr.check_dists(tmp_path)


# --- wheel smoke --------------------------------------------------------------------


def test_wheel_smoke_runs_install_and_notices(tmp_path: Path) -> None:
    make_wheel(tmp_path / "p.whl")
    runner = fake_runner(output="ABSOLUTELY NO WARRANTY")
    rr.wheel_smoke(tmp_path, runner)
    calls = runner.calls  # type: ignore[attr-defined]
    assert [c[0] for c in calls[:2]] == ["uv", "uv"]
    assert calls[2][-1] == "--version"
    assert calls[3][-1] == "--license"


def test_wheel_smoke_failures(tmp_path: Path) -> None:
    with pytest.raises(rr.CheckFailed, match="no wheel"):
        rr.wheel_smoke(tmp_path, fake_runner())
    make_wheel(tmp_path / "p.whl")
    with pytest.raises(rr.CheckFailed, match="failed"):
        rr.wheel_smoke(tmp_path, fake_runner({"uv": 1}))
    with pytest.raises(rr.CheckFailed, match="legal notice"):
        rr.wheel_smoke(tmp_path, fake_runner(output="n1mm-scope-bridge 0.1.0"))


# --- default steps and main ---------------------------------------------------------


def test_default_steps_cover_the_release_checklist() -> None:
    steps = rr.default_steps(fake_runner())
    names = [s.name for s in steps]
    assert names[0] == "Locked clean environment"
    assert any("licensing" in n for n in names)
    assert any("hook" in n.lower() for n in names)
    assert {s.name for s in steps if s.windows_only} >= {
        "GUI self-test",
        "Installer silent install/run/uninstall",
    }
    pending = [s for s in steps if s.disabled_reason]
    assert all(s.disabled_reason.startswith("added by #") for s in pending)


def test_default_build_step_reports_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rr, "DIST", tmp_path / "dist")
    build = next(s for s in rr.default_steps(fake_runner({"uv": 2})) if s.name.startswith("Build"))
    assert build.action is not None
    with pytest.raises(rr.CheckFailed, match="uv build failed"):
        build.action()
    ok_build = next(s for s in rr.default_steps(fake_runner()) if s.name.startswith("Build"))
    assert ok_build.action is not None
    ok_build.action()


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


def test_main_skipped_windows_steps_are_not_releasable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    steps = [
        rr.Step("win", ("w",), windows_only=True),
        rr.Step("later", disabled_reason="added by #6"),
    ]
    code = rr.main(
        ["--report", str(tmp_path / "r.md"), "--skip-windows-only"],
        steps=steps,
        meta={},
        runner=fake_runner(),
    )
    assert code == 1
    assert "NOT RELEASABLE" in capsys.readouterr().err


def test_environment_metadata() -> None:
    meta = rr.environment()
    assert set(meta) == {"commit", "ref", "platform", "python", "date (UTC)"}


# --- end-to-end replay step ------------------------------------------------------------

SPECTRUM = (
    (
        "<Spectrum><app>a</app><Name>FT-710</Name><LowScopeFrequency>1</LowScopeFrequency>"
        "<HighScopeFrequency>2</HighScopeFrequency><ScalingFactor>1</ScalingFactor>"
        "<DataCount>850</DataCount><SpectrumData>{}</SpectrumData></Spectrum>"
    )
    .format(",".join(["7"] * 850))
    .encode()
)


def udp_runner(packets: list[bytes], code: int = 0) -> rr.Runner:
    """Pretends to be the bridge: sends ``packets`` to the --port in the command."""

    def run(cmd: Sequence[str]) -> tuple[int, str]:
        port = int(cmd[cmd.index("--port") + 1])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
            for p in packets:
                tx.sendto(p, ("127.0.0.1", port))
        return code, "bridge output"

    return run


def test_e2e_replay_accepts_valid_packets() -> None:
    rr.e2e_replay(udp_runner([SPECTRUM] * rr.MIN_PACKETS))


@pytest.mark.parametrize(
    ("packets", "code", "message"),
    [
        ([SPECTRUM] * 6, 3, "exited 3"),
        ([SPECTRUM] * 2, 0, "got 2 packets"),
        ([b"<Spectrum>"] * 6, 0, "invalid"),
        ([b"<Other/>"] * 6, 0, "N1MM <Spectrum> format"),
    ],
)
def test_e2e_replay_failures(packets: list[bytes], code: int, message: str) -> None:
    with pytest.raises(rr.CheckFailed, match=message):
        rr.e2e_replay(udp_runner(packets, code))


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
    assert mypy.command[-2:] == ("--exclude", rr.GUI_PATHS)
    gui = next(s for s in steps if s.name == "GUI self-test")
    assert gui.disabled_reason == rr.GUI_SKIP
    monkeypatch.delenv("UV_NO_GROUP", raising=False)
    code = rr.main(
        ["--report", str(tmp_path / "r.md"), "--skip-gui"],
        steps=[rr.Step("gui", disabled_reason=rr.GUI_SKIP)],
        meta={},
        runner=fake_runner(),
    )
    assert code == 0
    assert os.environ["UV_NO_GROUP"] == "gui-dev"
    capsys.readouterr()
