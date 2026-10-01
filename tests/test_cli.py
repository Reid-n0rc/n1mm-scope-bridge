# SPDX-License-Identifier: GPL-3.0-only
import subprocess
import sys

import pytest

from n1mm_scope_bridge import __version__
from n1mm_scope_bridge.cli import main


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_args_reports_placeholder(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "not implemented" in capsys.readouterr().out


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
