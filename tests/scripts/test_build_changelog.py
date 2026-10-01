# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from pathlib import Path

import build_changelog as bc
import pytest

CHANGELOG = """# Changelog

Intro.

## [Unreleased]

See `changelog.d/`.

## [0.1.0] - 2026-01-01

### Added

- First. (#1)
"""


def frag(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_fragment(tmp_path: Path) -> None:
    f = bc.parse_fragment(frag(tmp_path, "30.added.2.md", "  UDP control.\n"))
    assert (f.issue, f.kind, f.text) == (30, "added", "UDP control.")


@pytest.mark.parametrize("name", ["added.md", "30.new.md", "30.added.txt.md", "x30.fixed.md"])
def test_bad_fragment_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(bc.FragmentError, match="name it"):
        bc.parse_fragment(frag(tmp_path, name, "x"))


def test_empty_fragment(tmp_path: Path) -> None:
    with pytest.raises(bc.FragmentError, match="empty"):
        bc.parse_fragment(frag(tmp_path, "3.fixed.md", "\n"))


def test_render_groups_and_orders(tmp_path: Path) -> None:
    frag(tmp_path, "README.md", "ignored")
    frag(tmp_path, "9.fixed.md", "Fixed thing.")
    frag(tmp_path, "7.added.md", "- Second\nwith a continuation line.")
    frag(tmp_path, "3.added.md", "First.")
    frag(tmp_path, "5.security.md", "Locked down.")
    text = bc.render(bc.load_fragments(tmp_path))
    assert text == (
        "### Added\n\n- First. (#3)\n- Second (#7)\n  with a continuation line.\n\n"
        "### Fixed\n\n- Fixed thing. (#9)\n\n"
        "### Security\n\n- Locked down. (#5)\n"
    )


def test_release_inserts_version_section(tmp_path: Path) -> None:
    frags = [bc.parse_fragment(frag(tmp_path, "30.added.md", "UDP control."))]
    out = bc.release(CHANGELOG, frags, "0.2.0", "2026-10-02")
    assert (
        out.index("## [Unreleased]")
        < out.index("## [0.2.0] - 2026-10-02")
        < out.index("## [0.1.0]")
    )
    assert "- UDP control. (#30)" in out
    assert "\n\n\n" not in out


@pytest.mark.parametrize(
    ("changelog", "version", "fragments", "message"),
    [
        (CHANGELOG, "two", True, "must look like"),
        (CHANGELOG, "0.2.0", False, "no changelog fragments"),
        ("# Changelog\n", "0.2.0", True, "no '## \\[Unreleased\\]'"),
    ],
)
def test_release_errors(
    tmp_path: Path, changelog: str, version: str, fragments: bool, message: str
) -> None:
    frags = [bc.parse_fragment(frag(tmp_path, "1.added.md", "x"))] if fragments else []
    with pytest.raises(bc.FragmentError, match=message):
        bc.release(changelog, frags, version, "2026-10-02")


def test_rc_versions_allowed(tmp_path: Path) -> None:
    frags = [bc.parse_fragment(frag(tmp_path, "1.added.md", "x"))]
    assert "## [0.2.0-rc1]" in bc.release(CHANGELOG, frags, "0.2.0-rc1", "2026-10-02")


@pytest.mark.parametrize(
    ("changed", "labels", "ok"),
    [
        (["src/x.py", "changelog.d/30.added.md"], [], True),
        (["src/x.py"], [], False),
        (["src/x.py", "changelog.d/README.md"], [], False),
        (["src/x.py"], ["no-changelog"], True),
        (["changelog.d/30.notes.md"], [], False),
    ],
)
def test_check_pr(changed: list[str], labels: list[str], ok: bool) -> None:
    assert (bc.check_pr(changed, labels) == []) is ok


def test_main_preview_release_and_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    frags = tmp_path / "changelog.d"
    frags.mkdir()
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    common = ["--fragments", str(frags), "--changelog", str(changelog)]
    assert bc.main(["--preview", *common]) == 0
    assert "(no unreleased changes)" in capsys.readouterr().out
    frag(frags, "30.added.md", "UDP control.")
    assert bc.main(["--preview", *common]) == 0
    assert "- UDP control. (#30)" in capsys.readouterr().out
    assert bc.main(["--version", "0.2.0", "--date", "2026-10-02", *common]) == 0
    assert "## [0.2.0] - 2026-10-02" in changelog.read_text(encoding="utf-8")
    assert list(frags.iterdir()) == []
    assert bc.main(["--version", "0.3.0", *common]) == 1
    assert "no changelog fragments" in capsys.readouterr().err
    assert bc.main(["--check-pr", "src/a.py"]) == 1
    assert "::error::Add a changelog fragment" in capsys.readouterr().out
    assert bc.main(["--check-pr", "src/a.py", "--label", "no-changelog"]) == 0


def test_repository_fragments_are_valid() -> None:
    fragments = bc.load_fragments()
    assert all(f.kind in bc.TYPES for f in fragments)
