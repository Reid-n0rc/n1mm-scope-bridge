# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Guards GPLv3 compliance for this repo and the wfview-derived code (issue #12)."""

from __future__ import annotations

import ast
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PY_FILES = sorted(
    p for d in ("src", "tests", "scripts") for p in (ROOT / d).rglob("*.py") if p.is_file()
)
WFVIEW_NOTICE = (
    "wfview is copyright 2017-2026 Elliott H. Liggett (W6EL) and Phil Taylor",
    "(M0VSE). All rights reserved. wfview source code is licensed via the GNU",
)
LICENSE_FILES = ["LICENSE", "NOTICE", "THIRD_PARTY.md"]


DERIVED_MARKER = "# Portions derived from wfview"


def _derived_from_wfview(text: str) -> bool:
    """Files that declare wfview-derived content in their header comment."""
    return DERIVED_MARKER in text.split('"""', 1)[0]


def test_there_are_python_files() -> None:
    assert len(PY_FILES) > 5


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_python_file_has_spdx_headers(path: Path) -> None:
    head = path.read_text(encoding="utf-8").splitlines()[:3]
    assert head[0] == "# SPDX-License-Identifier: GPL-3.0-only"
    assert any(line.startswith("# SPDX-FileCopyrightText: ") for line in head[1:])


def test_no_undeclared_wfview_derivation() -> None:
    """A module docstring that says it derives from wfview needs the header marker."""
    for path in PY_FILES:
        text = path.read_text(encoding="utf-8")
        doc = ast.get_docstring(ast.parse(text)) or ""
        if "derived from wfview" in doc.lower():
            assert _derived_from_wfview(text), f"{path.name} lacks the wfview header block"


def test_derived_files_exist() -> None:
    derived = [p for p in PY_FILES if _derived_from_wfview(p.read_text(encoding="utf-8"))]
    names = {p.name for p in derived}
    assert {"yaesu_scope.py", "ft710.py"} <= names


@pytest.mark.parametrize(
    "path",
    [p for p in PY_FILES if _derived_from_wfview(p.read_text(encoding="utf-8"))],
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_wfview_derived_files_keep_notices(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    header = text.split('"""', 1)[0]
    for line in WFVIEW_NOTICE:
        assert line in header, f"missing verbatim wfview notice: {line!r}"
    assert "SPDX-FileCopyrightText: 2017-2026 Elliott H. Liggett (W6EL)" in header
    assert "Modified by " in header, "GPLv3 5(a): derived files need a dated modification notice"
    assert "under the terms of the GNU General Public License" in header
    assert "WITHOUT\n# ANY WARRANTY" in header


def test_notice_file_reproduces_wfview_notice() -> None:
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    for line in WFVIEW_NOTICE:
        assert line.strip() in notice
    assert "Copyright 2017-2024 Elliott H. Liggett W6EL and Phil E. Taylor M0VSE" in notice
    assert "never" in notice  # FTDI libraries are never distributed
    assert "distributed with it" in notice


def test_license_is_gplv3_text() -> None:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 29 June 2007" in text


def test_pyproject_ships_license_files() -> None:
    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == "GPL-3.0-only"
    assert project["license-files"] == LICENSE_FILES


def test_third_party_records_wfview() -> None:
    text = (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert "### wfview" in text
    assert "All rights reserved" in text
    assert "never bundled" in text.lower()


@pytest.mark.slow
def test_built_wheel_contains_license_files(tmp_path: Path) -> None:
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"uv build unavailable: {result.stderr.strip()[:200]}")
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
    for name in LICENSE_FILES:
        assert any(n.endswith(f".dist-info/licenses/{name}") for n in names), name
