# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import io
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApi
from frames import make_ft4222_frame

from n1mm_scope_bridge import __version__
from n1mm_scope_bridge.cli import LatestStatus, format_status, main, supervise
from n1mm_scope_bridge.radios.base import ScopeStatus
from n1mm_scope_bridge.transport.ft4222 import LibraryNotFound
from n1mm_scope_bridge.transport.replay import CaptureReader, CaptureWriter

FIXTURE = Path(__file__).parent / "fixtures" / "ft710_synthetic.cap"


def cli(*argv: str, api: FakeApi | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()

    def loader(lib_dir: str | None) -> Any:
        if api is None:
            raise LibraryNotFound("Could not load FTDI's LibFT4222/D2XX libraries")
        return api

    code = main(list(argv), api_loader=loader, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def listener() -> Any:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(5)
        yield rx


# --- legal notices and help -------------------------------------------------------


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


def test_list_radios() -> None:
    code, out, _ = cli("list-radios")
    assert code == 0
    assert "ft710" in out
    assert "FT-710" in out


# --- run -----------------------------------------------------------------------------


def test_run_replay_streams_to_n1mm(listener: socket.socket) -> None:
    port = listener.getsockname()[1]
    code, _, err = cli(
        "run", "--replay", str(FIXTURE), "--loop", "--duration", "0.6",
        "--port", str(port), "--rate", "10", "--name", "Shack FT-710",
    )  # fmt: skip
    assert code == 0
    root = ET.fromstring(listener.recvfrom(65535)[0])
    assert root.findtext("Name") == "Shack FT-710"
    assert root.findtext("DataCount") == "850"
    assert "Streaming FT-710 to N1MM+ at 127.0.0.1:" in err
    assert "VFO 14.074000 MHz" in err


def test_run_radio_streams_with_fake_device(listener: socket.socket) -> None:
    port = listener.getsockname()[1]
    api = FakeApi(repeat=make_ft4222_frame())
    code, _, _ = cli("run", "--duration", "0.4", "--port", str(port), "--rate", "10", api=api)
    assert code == 0
    assert ET.fromstring(listener.recvfrom(65535)[0]).findtext("LowScopeFrequency") == "14024"


def test_run_reports_missing_ftdi_library() -> None:
    code, _, err = cli("run", "--duration", "0.1")
    assert code == 1
    assert err.startswith("error: Could not load FTDI")
    assert "Traceback" not in err


def test_run_rejects_capture_from_another_radio(tmp_path: Path) -> None:
    path = tmp_path / "other.cap"
    with path.open("wb") as fh:
        CaptureWriter(fh, "FTDX10", 4096)
    code, _, err = cli("run", "--replay", str(path))
    assert code == 1
    assert "recorded from a FTDX10, not a FT-710" in err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("run", "--radio", "ic7300"), "unknown radio"),
        (("run", "--replay", "missing.cap"), "missing.cap"),
        (("run", "--replay", str(FIXTURE), "--scaling", "0"), "scaling"),
        (("run", "--replay", str(FIXTURE), "--rate", "50"), "rate"),
        (("run", "--replay", str(FIXTURE), "--name", ""), "name"),
    ],
)
def test_run_user_errors(argv: tuple[str, ...], message: str) -> None:
    code, _, err = cli(*argv)
    assert code == 1
    assert message in err


# --- record and probe ------------------------------------------------------------------


def test_record_writes_capture(tmp_path: Path) -> None:
    out = tmp_path / "cap.cap"
    code, _, err = cli("record", "--frames", "3", str(out), api=FakeApi(make_ft4222_frame() * 5))
    assert code == 0
    assert len(list(CaptureReader(out))) == 3
    assert "Recorded 3 frames" in err


def test_record_rejects_zero_frames(tmp_path: Path) -> None:
    code, _, err = cli("record", "--frames", "0", str(tmp_path / "x.cap"), api=FakeApi())
    assert code == 1
    assert "--frames" in err


def test_probe_reports_radio_and_center_tip() -> None:
    code, out, _ = cli("probe", api=FakeApi(make_ft4222_frame(scope_mode=0x07)))
    assert code == 0
    assert "FTDI libraries loaded." in out
    assert "FT-710 found on 'FT4222 A'." in out
    assert "VFO-A 14074000 Hz" in out
    assert "Center mode" in out
    code, out, _ = cli("probe", api=FakeApi(make_ft4222_frame()))
    assert "Center mode" not in out


# --- supervise and status ---------------------------------------------------------------


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
