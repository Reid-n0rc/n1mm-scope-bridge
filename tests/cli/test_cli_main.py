# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import importlib
import io
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from cliutil import cli

from n1mm_scope_bridge import __version__
from n1mm_scope_bridge import cli as cli_pkg
from n1mm_scope_bridge.cli import LatestStatus, discover_commands, format_status, main, supervise
from n1mm_scope_bridge.radios.base import ScopeStatus


def test_version_flag_prints_version_and_notices(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert __version__ in out
    assert "ABSOLUTELY NO WARRANTY" in out
    assert "Elliott H. Liggett (W6EL)" in out
    assert "GNU General Public License version 3" in out


def test_license_flag_prints_full_notice(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--license"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "version 3 of the License" in out
    assert "corresponding source" in out


def test_no_command_prints_help() -> None:
    code, out, _ = cli()
    assert code == 0
    for command in ("run", "record", "probe", "list-radios"):
        assert command in out
    assert "ABSOLUTELY NO WARRANTY" in out


def test_unknown_flag_is_rejected() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--bogus"])
    assert exc.value.code == 2


def test_module_entry_point_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "n1mm_scope_bridge", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout


class FakePipe:
    def __init__(self, interrupt: bool = False, runs: int = 3) -> None:
        self.interrupt = interrupt
        self.runs = runs
        self.stopped = 0

    @property
    def alive(self) -> bool:
        return self.runs > 0

    def join(self, timeout: float | None = None) -> bool:
        if self.interrupt and self.stopped == 0:
            raise KeyboardInterrupt
        self.runs -= 1
        return not self.alive

    def stop(self) -> None:
        self.stopped += 1


def test_supervise_reports_until_pipeline_ends() -> None:
    reports: list[int] = []
    pipe = FakePipe(runs=3)
    supervise(pipe, duration=None, report=lambda: reports.append(1))  # type: ignore[arg-type]
    assert len(reports) == 3
    assert pipe.stopped == 1


def test_supervise_stops_on_ctrl_c() -> None:
    pipe = FakePipe(interrupt=True)
    supervise(pipe, duration=None, report=lambda: None)  # type: ignore[arg-type]
    assert pipe.stopped == 1


def test_supervise_honors_duration() -> None:
    now = [0.0]

    def tick() -> float:
        now[0] += 1.0
        return now[0]

    pipe = FakePipe(runs=100)
    supervise(pipe, duration=2.0, report=lambda: None, clock=tick)  # type: ignore[arg-type]
    assert pipe.runs > 90
    assert pipe.stopped == 1


def test_format_status() -> None:
    class Stats:
        frames_read, emitted, frames_dropped, bad_frames = 10, 4, 1, 2

    class Pipe:
        def stats(self) -> Stats:
            return Stats()

    status = ScopeStatus(14_074_000, 20_000, "center", "Center (Normal)")
    text = format_status(status, Pipe())  # type: ignore[arg-type]
    assert text == (
        "VFO 14.074000 MHz, span 20 kHz, Center (Normal) | read 10 | sent 4 | dropped 1 | bad 2"
    )
    assert format_status(None, Pipe()).startswith("waiting for radio")  # type: ignore[arg-type]


def test_latest_status_holder() -> None:
    holder = LatestStatus()
    assert holder.value is None
    status = ScopeStatus(1, 2, "center", "x")
    holder.update(status)
    assert holder.value is status


# --- command discovery (#44) ---------------------------------------------------------------

COMMAND_TEMPLATE = """
NAME = {name!r}
HELP = "test command"
ORDER = {order}


def register(sub):
    return sub.add_parser(NAME, help=HELP)


def run(args, ctx):
    print("ran " + NAME, file=ctx.out)
    return 7
"""


def make_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, modules: dict[str, str]
) -> ModuleType:
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for module, text in modules.items():
        (pkg / f"{module}.py").write_text(text, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return importlib.import_module(name)


def test_builtin_commands_are_discovered_in_order() -> None:
    assert list(discover_commands()) == ["run", "record", "probe", "list-radios"]


def test_a_new_command_needs_only_a_new_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkg = make_package(
        tmp_path,
        monkeypatch,
        "extra_commands_ok",
        {
            "zeta": COMMAND_TEMPLATE.format(name="zeta", order=5),
            "alpha": COMMAND_TEMPLATE.format(name="alpha", order=50),
        },
    )
    found = cli_pkg.discover_commands(pkg)
    assert list(found) == ["zeta", "alpha"]  # ORDER, not file name
    monkeypatch.setattr(cli_pkg, "_commands_pkg", pkg)
    monkeypatch.setattr(cli_pkg.discover_commands, "__defaults__", (pkg,))
    out = io.StringIO()
    assert main(["zeta"], out=out, err=io.StringIO()) == 7
    assert out.getvalue() == "ran zeta\n"


def test_incomplete_command_module_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkg = make_package(tmp_path, monkeypatch, "extra_commands_bad", {"broken": "NAME = 'broken'\n"})
    with pytest.raises(RuntimeError, match="lacks HELP, ORDER, register, run"):
        discover_commands(pkg)


def test_duplicate_command_names_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkg = make_package(
        tmp_path,
        monkeypatch,
        "extra_commands_dup",
        {
            "a": COMMAND_TEMPLATE.format(name="same", order=1),
            "b": COMMAND_TEMPLATE.format(name="same", order=2),
        },
    )
    with pytest.raises(RuntimeError, match="same NAME"):
        discover_commands(pkg)
