# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
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


def test_version_shows_legal_notices(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    out = capsys.readouterr().out
    assert "ABSOLUTELY NO WARRANTY" in out
    assert "wfview" in out
    assert "Elliott H. Liggett (W6EL)" in out
    assert "GNU General Public License version 3" in out
    assert "--license" in out


def test_license_flag_prints_full_notice(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--license"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "version 3 of the License" in out
    assert "WITHOUT\nANY WARRANTY" in out
    assert "corresponding source" in out
    assert "https://github.com/Reid-n0rc/n1mm-scope-bridge" in out


def test_help_shows_legal_notice(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "ABSOLUTELY NO WARRANTY" in capsys.readouterr().out
