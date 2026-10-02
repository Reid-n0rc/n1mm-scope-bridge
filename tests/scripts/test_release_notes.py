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


@pytest.mark.parametrize(
    ("tag", "package"),
    [("v0.1.2", "0.1.2"), ("v0.1.0-rc2", "0.1.0rc2"), ("v10.2.3-rc11", "10.2.3rc11")],
)
def test_package_version_comes_from_the_tag(tag: str, package: str) -> None:
    assert rn.parse_tag(tag).package_version == package


def _fake_checkout(root: Path, version: str = "0.1.0") -> Path:
    (root / "src" / "n1mm_scope_bridge").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "n1mm-scope-bridge"\nversion = "{version}"\n\n'
        '[tool.ruff]\ntarget-version = "py310"\n',
        encoding="utf-8",
    )
    (root / "src" / "n1mm_scope_bridge" / "__init__.py").write_text(
        f'"""Doc."""\n\n__version__ = "{version}"\n', encoding="utf-8"
    )
    (root / "uv.lock").write_text(
        'version = 1\n\n[[package]]\nname = "other"\nversion = "9.9.9"\n\n'
        f'[[package]]\nname = "n1mm-scope-bridge"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    return root


def test_stamp_version_writes_every_location(tmp_path: Path) -> None:
    root = _fake_checkout(tmp_path)
    assert rn.stamp_version(root, "0.1.2rc1") == [rel for rel, _ in rn.VERSION_FILES]
    assert set(rn.project_versions(root).values()) == {"0.1.2rc1"}
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'target-version = "py310"' in pyproject  # only [project] version touched
    assert 'name = "other"\nversion = "9.9.9"' in (root / "uv.lock").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", ["0.1", "v0.1.2", "0.1.2-rc1", "0.1.2rc0", "", "0.1.2; rm"])
def test_stamp_version_rejects_malformed(tmp_path: Path, bad: str) -> None:
    with pytest.raises(rn.ReleaseError, match="malformed"):
        rn.stamp_version(_fake_checkout(tmp_path), bad)


def test_stamp_version_reports_missing_location(tmp_path: Path) -> None:
    root = _fake_checkout(tmp_path)
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    with pytest.raises(rn.ReleaseError, match=re.escape("no version found in uv.lock")):
        rn.stamp_version(root, "0.2.0")


def test_stamp_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _fake_checkout(tmp_path)
    assert rn.main(["stamp", "--version", "0.3.0", "--root", str(root)]) == 0
    assert "stamped 0.3.0" in capsys.readouterr().out
    assert rn.main(["stamp", "--version", "nope", "--root", str(root)]) == 1


def test_repo_versions_agree() -> None:
    """pyproject.toml, __version__ and uv.lock must carry the same version.

    A manual bump of only pyproject.toml would otherwise ship an app that
    reports a different version than its installer and wheel.
    """
    versions = rn.project_versions(rn.ROOT)
    assert len(set(versions.values())) == 1, versions


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


def test_missing_changelog_section_is_noted_not_fatal() -> None:
    text = rn.release_notes(rn.parse_tag("v0.9.0"), CHANGELOG)
    assert rn.MISSING_SECTION in text
    assert "## Changes in 0.9.0" in text


def test_dry_run_tolerates_missing_section(tmp_path: Path) -> None:
    text = rn.release_notes(rn.parse_tag("v0.9.0-rc1"), CHANGELOG, dry_run=True)
    assert rn.DRY_RUN_PLACEHOLDER in text
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    out = tmp_path / "notes.md"
    args = ["notes", "--tag", "v0.9.0", "--out", str(out), "--changelog", str(changelog)]
    assert rn.main(args) == 0
    assert rn.MISSING_SECTION in out.read_text(encoding="utf-8")
    assert rn.main([*args, "--dry-run"]) == 0
    assert rn.DRY_RUN_PLACEHOLDER in out.read_text(encoding="utf-8")


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


def test_main_meta_derives_version_from_tag(capsys: pytest.CaptureFixture[str]) -> None:
    # The tag decides the version; pyproject.toml is not consulted (#167).
    assert rn.main(["meta", "--tag", "v999.0.0-rc1"]) == 0
    out = capsys.readouterr().out
    assert "version=999.0.0rc1" in out
    assert "base_version=999.0.0" in out
    assert "prerelease=true" in out
    assert rn.main(["meta", "--tag", "v0.1.2"]) == 0
    out = capsys.readouterr().out
    assert "version=0.1.2" in out
    assert "prerelease=false" in out
    assert rn.main(["meta", "--tag", "0.1.2"]) == 1


def test_rc_notes_and_assets_use_the_rc_package_version(tmp_path: Path) -> None:
    notes = rn.release_notes(rn.parse_tag("v0.1.0-rc2"), CHANGELOG)
    assert "`n1mm-scope-bridge-setup-0.1.0rc2.exe`" in notes
    assert rn.required_assets("0.1.0rc2") == ["n1mm-scope-bridge-setup-0.1.0rc2.exe"]
    (tmp_path / "n1mm-scope-bridge-setup-0.1.0rc2.exe").write_bytes(b"x")
    assert rn.main(["assets", "--tag", "v0.1.0-rc2", str(tmp_path)]) == 0


def test_release_is_the_installer_only() -> None:
    """The maintainer wants exactly one release file: the universal installer (#167)."""
    assert rn.required_assets("0.1.2") == ["n1mm-scope-bridge-setup-0.1.2.exe"]
    notes = rn.release_notes(rn.parse_tag("v0.1.2"), CHANGELOG)
    assert "one installer for all Windows PCs" in notes
    for gone in (bwa.zip_name("0.1.2", "x64"), ".whl", ".tar.gz", "`SHA256SUMS`"):
        assert gone not in notes


def test_notes_carry_checksum_run_link_and_source_offer() -> None:
    notes = rn.release_notes(
        rn.parse_tag("v0.1.2"),
        CHANGELOG,
        installer_sha256="ab" * 32,
        run_url="https://github.com/o/r/actions/runs/1",
    )
    assert "ab" * 32 in notes
    assert "(https://github.com/o/r/actions/runs/1)" in notes
    assert "Complete corresponding source (GPLv3): the **Source code** archives" in notes
    assert notes.count(rn.FILES_START) == notes.count(rn.FILES_END) == 1
    bare = rn.release_notes(rn.parse_tag("v0.1.2"), CHANGELOG)
    assert "actions/runs" not in bare
    assert "SHA-256 of" not in bare


def test_missing_and_extra_assets() -> None:
    exe = "n1mm-scope-bridge-setup-0.1.0.exe"
    assert rn.missing_assets("0.1.0", [exe]) == []
    assert rn.missing_assets("0.1.0", []) == [exe]
    assert rn.extra_assets("0.1.0", [exe]) == []
    assert rn.extra_assets("0.1.0", [exe, "SHA256SUMS", "a.zip"]) == ["SHA256SUMS", "a.zip"]


def test_assets_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exe = tmp_path / "n1mm-scope-bridge-setup-0.1.0.exe"
    exe.write_bytes(b"x")
    assert rn.main(["assets", "--tag", "v0.1.0", str(tmp_path)]) == 0
    assert "release files OK" in capsys.readouterr().out
    (tmp_path / "screenshots.zip").write_bytes(b"x")
    assert rn.main(["assets", "--tag", "v0.1.0", str(tmp_path)]) == 1
    assert "only the installer may be released; remove: screenshots.zip" in (
        capsys.readouterr().err
    )
    exe.unlink()
    assert rn.main(["assets", "--tag", "v0.1.0", str(tmp_path)]) == 1
    assert "missing required files: n1mm-scope-bridge-setup-0.1.0.exe" in (capsys.readouterr().err)


def test_merge_keeps_maintainer_notes_and_refreshes_ours(tmp_path: Path) -> None:
    ours = rn.release_notes(rn.parse_tag("v0.1.2"), CHANGELOG, installer_sha256="cd" * 32)
    mine = "## What's Changed\n* thing by @me\n"
    merged = rn.merge_notes(mine, ours, replace=False)
    assert merged.startswith("## What's Changed")
    assert "cd" * 32 in merged
    again = rn.merge_notes(merged, ours.replace("cd" * 32, "ef" * 32), replace=False)
    assert "cd" * 32 not in again
    assert again.count(rn.FILES_START) == 1
    assert rn.merge_notes(mine, ours, replace=True) == ours
    assert rn.merge_notes("  ", ours, replace=False) == ours
    assert rn.merge_notes(mine, "plain", replace=False).endswith("plain\n")
    old, new, out = tmp_path / "old.md", tmp_path / "new.md", tmp_path / "out.md"
    old.write_text(mine, encoding="utf-8")
    new.write_text(ours, encoding="utf-8")
    args = ["merge", "--existing", str(old), "--new", str(new), "--out", str(out)]
    assert rn.main(args) == 0
    assert out.read_text(encoding="utf-8").startswith("## What's Changed")
    assert rn.main([*args, "--replace"]) == 0
    assert out.read_text(encoding="utf-8") == ours


def test_notes_command_hashes_the_installer(tmp_path: Path) -> None:
    changelog, out = tmp_path / "CHANGELOG.md", tmp_path / "notes.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"installer")
    argv = ["notes", "--tag", "v0.1.0", "--out", str(out), "--changelog", str(changelog)]
    assert rn.main([*argv, "--installer", str(exe), "--run-url", "https://x.invalid/r"]) == 0
    text = out.read_text(encoding="utf-8")
    assert hashlib.sha256(b"installer").hexdigest() in text
    assert "(https://x.invalid/r)" in text
