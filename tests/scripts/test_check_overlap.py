# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import json
from collections.abc import Sequence

import check_overlap as co
import pytest

BODY = """## Goal
x

## Files
- create `src/n1mm_scope_bridge/control.py`, `tests/test_control.py`, `docs/user/udp-control.md`
- modify `src/n1mm_scope_bridge/{cli,settings}.py`, `scripts/regression_steps/`
- `tests/cli/test_*.py`; see `https://example.com/x.py` and `--flag`

## Test plan
`not/a/planned/file.py`
"""

PRS = [
    {"number": 50, "title": "GUI", "files": [{"path": "src/n1mm_scope_bridge/gui/app.py"}]},
    {"number": 51, "title": "Settings", "files": [{"path": "src/n1mm_scope_bridge/settings.py"}]},
    {"number": 52, "title": "Steps", "files": [{"path": "scripts/regression_steps/30_gui.py"}]},
    {"number": 53, "title": "No files", "files": None},
]


def fake_gh(body: str = BODY, prs: list[dict[str, object]] | None = None) -> co.Gh:
    def gh(args: Sequence[str]) -> str:
        if args[:2] == ["pr", "list"]:
            return json.dumps(PRS if prs is None else prs)
        if args[:2] == ["issue", "view"]:
            return json.dumps({"body": body})
        raise AssertionError(args)

    return gh


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("a/{b,c}.py", ["a/b.py", "a/c.py"]),
        ("{x,y}/{1,2}", ["x/1", "x/2", "y/1", "y/2"]),
        ("plain.py", ["plain.py"]),
    ],
)
def test_expand_braces(pattern: str, expected: list[str]) -> None:
    assert co.expand_braces(pattern) == expected


def test_files_from_issue_reads_only_the_files_section() -> None:
    assert co.files_from_issue(BODY) == [
        "src/n1mm_scope_bridge/control.py",
        "tests/test_control.py",
        "docs/user/udp-control.md",
        "src/n1mm_scope_bridge/cli.py",
        "src/n1mm_scope_bridge/settings.py",
        "scripts/regression_steps/",
        "tests/cli/test_*.py",
    ]
    assert co.files_from_issue("no files section") == []
    assert co.files_from_issue("") == []


@pytest.mark.parametrize(
    ("planned", "changed", "hit"),
    [
        ("a/b.py", "a/b.py", True),
        ("a/", "a/b/c.py", True),
        ("a", "a/b.py", True),
        ("a", "ab.py", False),
        ("tests/cli/test_*.py", "tests/cli/test_run.py", True),
        ("tests/cli/test_*.py", "tests/test_cli.py", False),
    ],
)
def test_matches(planned: str, changed: str, hit: bool) -> None:
    assert co.matches(planned, changed) is hit


def test_issue_with_overlaps_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert co.main(["30"], gh=fake_gh()) == 1
    out = capsys.readouterr().out
    assert "overlaps PR #51 (Settings): src/n1mm_scope_bridge/settings.py" in out
    assert "PR #52" in out
    assert "PR #50" not in out


def test_issue_without_overlap_is_clear(capsys: pytest.CaptureFixture[str]) -> None:
    assert co.main(["30"], gh=fake_gh(prs=PRS[:1])) == 0
    assert "Clear to start" in capsys.readouterr().out


def test_issue_without_files_section_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    assert co.main(["30"], gh=fake_gh(body="## Goal\nx")) == 1
    assert "cannot check" in capsys.readouterr().out


def test_pr_mode_warns_but_never_fails(capsys: pytest.CaptureFixture[str]) -> None:
    prs = [
        *PRS,
        {
            "number": 54,
            "title": "Also settings",
            "files": [{"path": "src/n1mm_scope_bridge/settings.py"}],
        },
    ]
    assert co.main(["--pr", "51"], gh=fake_gh(prs=prs)) == 0
    out = capsys.readouterr().out
    assert out.startswith("::warning::PR #51 and PR #54 (Also settings) both change")


def test_pr_mode_no_overlap_and_unknown_pr(capsys: pytest.CaptureFixture[str]) -> None:
    assert co.main(["--pr", "50"], gh=fake_gh()) == 0
    assert "no file overlap" in capsys.readouterr().out
    assert co.main(["--pr", "99"], gh=fake_gh()) == 0
    assert "not open" in capsys.readouterr().out


def test_needs_issue_or_pr() -> None:
    with pytest.raises(SystemExit):
        co.main([], gh=fake_gh())
