# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import build_windows_app as bwa
import pytest
import release_notes as rn

CHANGELOG = """# Changelog

## [Unreleased]

See changelog.d.

## [0.2.0] - 2026-11-01

### Added

- Two (#2)

## [0.1.0] - 2026-10-15

### Added

- One (#1)
"""


@pytest.mark.parametrize(
    ("tag", "version", "rc"),
    [("v0.1.0", "0.1.0", None), ("v0.1.0-rc1", "0.1.0", 1), ("v10.20.30-rc12", "10.20.30", 12)],
)
def test_parse_tag(tag: str, version: str, rc: int | None) -> None:
    info = rn.parse_tag(tag)
    assert (info.version, info.rc, info.prerelease) == (version, rc, rc is not None)


@pytest.mark.parametrize("tag", ["0.1.0", "v0.1", "v0.1.0-rc0", "v0.1.0-beta1", "v0.1.0rc1", ""])
def test_parse_tag_rejects(tag: str) -> None:
    with pytest.raises(rn.ReleaseError, match=re.escape("vX.Y.Z")):
        rn.parse_tag(tag)


def test_check_project_version() -> None:
    pyproject = '[project]\nname = "x"\nversion = "0.1.0"\n\n[tool.x]\nversion = "9"\n'
    rn.check_project_version(rn.parse_tag("v0.1.0-rc2"), pyproject)
    with pytest.raises(
        rn.ReleaseError, match=re.escape("does not match pyproject.toml version 0.1.0")
    ):
        rn.check_project_version(rn.parse_tag("v0.2.0"), pyproject)
    with pytest.raises(rn.ReleaseError, match="no \\[project\\] version"):
        rn.check_project_version(rn.parse_tag("v0.1.0"), "[tool.x]\nversion = '1'\n")


def test_changelog_section() -> None:
    assert rn.changelog_section(CHANGELOG, "0.1.0") == "### Added\n\n- One (#1)"
    assert rn.changelog_section(CHANGELOG, "0.2.0") == "### Added\n\n- Two (#2)"
    assert rn.changelog_section(CHANGELOG, "0.3.0") is None
    assert rn.changelog_section(CHANGELOG, "0.1") is None  # no partial match


def test_release_notes_final_and_rc() -> None:
    final = rn.release_notes(rn.parse_tag("v0.1.0"), CHANGELOG)
    assert "## Changes in 0.1.0" in final
    assert "- One (#1)" in final
    assert "Release candidate" not in final
    assert "LibFT4222 is not included" in final
    rc = rn.release_notes(rn.parse_tag("v0.1.0-rc3"), CHANGELOG, report="**Result: PASS**")
    assert rc.startswith("**Release candidate 3 for 0.1.0.**")
    assert "<summary>Release regression report</summary>" in rc
    assert "**Result: PASS**" in rc


def test_release_notes_require_changelog_section() -> None:
    with pytest.raises(rn.ReleaseError, match=re.escape("build_changelog.py --version 0.9.0")):
        rn.release_notes(rn.parse_tag("v0.9.0"), CHANGELOG)


def test_dry_run_tolerates_missing_section(tmp_path: Path) -> None:
    text = rn.release_notes(rn.parse_tag("v0.9.0-rc1"), CHANGELOG, dry_run=True)
    assert rn.DRY_RUN_PLACEHOLDER in text
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    out = tmp_path / "notes.md"
    args = ["notes", "--tag", "v0.9.0", "--out", str(out), "--changelog", str(changelog)]
    assert rn.main(args) == 1
    assert rn.main([*args, "--dry-run"]) == 0


def test_sha256sums(tmp_path: Path) -> None:
    b = tmp_path / "b.zip"
    a = tmp_path / "a.whl"
    b.write_bytes(b"bbb")
    a.write_bytes(b"aaa")
    text = rn.sha256sums([b, a])
    assert text.splitlines() == [
        f"{hashlib.sha256(b'aaa').hexdigest()}  a.whl",
        f"{hashlib.sha256(b'bbb').hexdigest()}  b.zip",
    ]


def test_sha256sums_errors(tmp_path: Path) -> None:
    with pytest.raises(rn.ReleaseError, match="no files"):
        rn.sha256sums([])
    (tmp_path / "d1").mkdir()
    (tmp_path / "d2").mkdir()
    one, two = tmp_path / "d1" / "x.zip", tmp_path / "d2" / "x.zip"
    one.write_bytes(b"1")
    two.write_bytes(b"2")
    with pytest.raises(rn.ReleaseError, match="duplicate"):
        rn.sha256sums([one, two])


def test_main_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    report = tmp_path / "report.md"
    report.write_text("**Result: PASS**", encoding="utf-8")
    out = tmp_path / "notes.md"
    assert (
        rn.main(
            [
                "notes",
                "--tag",
                "v0.1.0-rc1",
                "--out",
                str(out),
                "--changelog",
                str(changelog),
                "--report",
                str(report),
            ]
        )
        == 0
    )
    assert "Result: PASS" in out.read_text(encoding="utf-8")
    missing = tmp_path / "none.md"
    assert (
        rn.main(
            [
                "notes",
                "--tag",
                "v0.1.0",
                "--out",
                str(out),
                "--changelog",
                str(changelog),
                "--report",
                str(missing),
            ]
        )
        == 0
    )
    file = tmp_path / "f.bin"
    file.write_bytes(b"x")
    sums = tmp_path / "SHA256SUMS"
    assert rn.main(["sums", "--out", str(sums), str(file)]) == 0
    assert sums.read_text(encoding="utf-8").endswith("  f.bin\n")
    assert rn.main(["notes", "--tag", "bad", "--out", str(out), "--changelog", str(changelog)]) == 1
    assert "error: tag 'bad'" in capsys.readouterr().err


def test_main_meta_uses_repo_pyproject(capsys: pytest.CaptureFixture[str]) -> None:
    version = re.search(
        r'^version = "([^"]+)"',
        (rn.ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert version is not None
    assert rn.main(["meta", "--tag", f"v{version[1]}-rc1"]) == 0
    out = capsys.readouterr().out
    assert f"version={version[1]}" in out
    assert "prerelease=true" in out
    assert rn.main(["meta", "--tag", "v999.0.0"]) == 1


def test_download_names_match_the_built_artifacts() -> None:
    """The notes name the zip exactly as build_windows_app.py produces it."""
    notes = rn.release_notes(rn.parse_tag("v0.1.0"), CHANGELOG)
    assert f"`{bwa.zip_name('0.1.0')}`" in notes
    assert "`n1mm-scope-bridge-0.1.0-win64.zip`" in notes
    assert "windows.zip" not in notes


def test_required_assets_include_screenshots_and_sources() -> None:
    names = rn.required_assets("0.1.0")
    assert "screenshots.zip" in names
    assert "regression-report.md" in names
    assert bwa.zip_name("0.1.0") in names
    assert "n1mm-scope-bridge-setup-0.1.0.exe" in names
    assert "n1mm_scope_bridge-0.1.0.tar.gz" in names  # GPLv3 corresponding source
    assert "n1mm_scope_bridge-0.1.0-py3-none-any.whl" in names


def test_missing_assets() -> None:
    all_names = rn.required_assets("0.1.0")
    assert rn.missing_assets("0.1.0", all_names) == []
    assert rn.missing_assets("0.1.0", [n for n in all_names if n != "screenshots.zip"]) == [
        "screenshots.zip"
    ]


def test_assets_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for name in rn.required_assets("0.1.0"):
        (tmp_path / name).write_bytes(b"x")
    assert rn.main(["assets", "--tag", "v0.1.0-rc1", str(tmp_path)]) == 0
    assert "required release files present" in capsys.readouterr().out
    (tmp_path / "screenshots.zip").unlink()
    assert rn.main(["assets", "--tag", "v0.1.0-rc1", str(tmp_path)]) == 1
    assert "missing required files: screenshots.zip" in capsys.readouterr().err


def test_release_notes_list_screenshots() -> None:
    assert "`screenshots.zip`" in rn.release_notes(rn.parse_tag("v0.1.0"), CHANGELOG)
