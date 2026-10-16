# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import close_linked_issues as cli
import pytest

REPO = "Reid-n0rc/n1mm-scope-bridge"
SHA = "0123456789abcdef"


def ref(number: int, owner: str = "Reid-n0rc", name: str = "n1mm-scope-bridge") -> dict[str, Any]:
    return {"number": number, "repository": {"name": name, "owner": {"login": owner}}}


def pr(**kw: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "state": "MERGED",
        "baseRefName": "dev",
        "mergeCommit": {"oid": SHA},
        "closingIssuesReferences": [ref(9)],
    }
    data.update(kw)
    return data


class FakeGh:
    def __init__(self, the_pr: dict[str, Any], states: dict[int, str] | None = None) -> None:
        self.the_pr = the_pr
        self.states = states or {}
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.calls.append(list(args))
        if args[:2] == ["pr", "view"]:
            return json.dumps(self.the_pr)
        if args[:2] == ["issue", "view"]:
            return json.dumps({"state": self.states.get(int(args[2]), "OPEN")})
        if args[:2] == ["issue", "close"]:
            return ""
        raise AssertionError(f"unexpected gh call {args}")

    def closed(self) -> list[int]:
        return [int(c[2]) for c in self.calls if c[:2] == ["issue", "close"]]


def test_one_open_issue_is_closed_with_comment(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr())
    assert cli.main(["220"], gh) == 0
    assert gh.closed() == [9]
    close = next(c for c in gh.calls if c[:2] == ["issue", "close"])
    assert close[close.index("--reason") + 1] == "completed"
    assert close[close.index("--repo") + 1] == REPO
    comment = close[close.index("--comment") + 1]
    assert comment == (
        "Closed by #220 (merged into dev as 0123456). Ships in the next release from master."
    )
    assert "#9: closed." in capsys.readouterr().out


def test_several_open_issues_are_all_closed() -> None:
    gh = FakeGh(pr(closingIssuesReferences=[ref(3), ref(4), ref(3)]))
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == [3, 4]


def test_already_closed_issue_is_skipped(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(closingIssuesReferences=[ref(3), ref(4)]), states={3: "CLOSED"})
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == [4]
    assert "#3: already closed, skipped." in capsys.readouterr().out


@pytest.mark.parametrize(
    "the_ref",
    [ref(5, owner="someone-else"), ref(5, name="other-repo"), {"repository": None}],
    ids=["other-owner", "other-repo", "no-repository"],
)
def test_cross_repo_reference_is_ignored(the_ref: dict[str, Any]) -> None:
    gh = FakeGh(pr(closingIssuesReferences=[the_ref]))
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == []


def test_repo_match_ignores_case() -> None:
    assert cli.same_repo_issues([ref(7, owner="reid-n0rc")], REPO) == [7]


@pytest.mark.parametrize("refs", [[], None], ids=["empty-list", "missing-field"])
def test_no_linked_issues_closes_nothing(
    refs: list[Any] | None, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(pr(closingIssuesReferences=refs))
    assert cli.main(["1", REPO], gh) == 0
    assert gh.closed() == []
    assert "links no issues" in capsys.readouterr().out


def test_unmerged_pr_closes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(state="CLOSED"))
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == []
    assert "not merged" in capsys.readouterr().out


def test_pr_into_another_branch_closes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(baseRefName="master"))
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == []
    assert "not 'dev'" in capsys.readouterr().out


def test_missing_merge_commit_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(mergeCommit=None))
    assert cli.main(["1"], gh) == 1
    assert "no merge commit" in capsys.readouterr().err


def test_gh_failure_exits_non_zero_with_message(capsys: pytest.CaptureFixture[str]) -> None:
    def failing(args: Sequence[str]) -> str:
        raise RuntimeError("gh pr failed: HTTP 502")

    assert cli.main(["12"], failing) == 1
    err = capsys.readouterr().err
    assert "could not close the issues linked by PR #12" in err
    assert "HTTP 502" in err


def test_invalid_json_from_gh_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["1"], lambda args: "not json") == 1
    assert "invalid JSON" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["abc"], ["1", REPO, "extra"]], ids=["none", "nan", "3"])
def test_bad_arguments_print_usage(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(argv, FakeGh(pr())) == 2
    assert "usage:" in capsys.readouterr().err


def test_fake_rejects_unexpected_calls() -> None:
    with pytest.raises(AssertionError):
        FakeGh(pr())(["api", "x"])
