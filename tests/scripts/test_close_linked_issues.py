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


def pr(**kw: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "merged": True,
        "base": {"ref": "dev"},
        "merge_commit_sha": SHA,
        "body": "Closes #9\n\nDetails.",
    }
    data.update(kw)
    return data


class FakeGh:
    """A fake ``gh``: one PR, issues open unless listed, ``pulls`` are pull requests."""

    def __init__(
        self,
        the_pr: dict[str, Any],
        states: dict[int, str] | None = None,
        pulls: Sequence[int] = (),
    ) -> None:
        self.the_pr = the_pr
        self.states = states or {}
        self.pulls = set(pulls)
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.calls.append(list(args))
        if args[0] == "api" and args[1].startswith(f"repos/{REPO}/pulls/"):
            return json.dumps(self.the_pr)
        if args[0] == "api" and args[1].startswith(f"repos/{REPO}/issues/"):
            number = int(args[1].rsplit("/", 1)[1])
            info: dict[str, Any] = {"number": number, "state": self.states.get(number, "open")}
            if number in self.pulls:
                info["pull_request"] = {"url": "x"}
            return json.dumps(info)
        if args[:2] == ["issue", "close"]:
            return ""
        raise AssertionError(f"unexpected gh call {args}")

    def closed(self) -> list[int]:
        return [int(c[2]) for c in self.calls if c[:2] == ["issue", "close"]]


def test_one_open_issue_is_closed_with_comment(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr())
    assert cli.main(["220"], gh) == 0
    assert gh.calls[0] == ["api", f"repos/{REPO}/pulls/220"]
    assert gh.closed() == [9]
    close = next(c for c in gh.calls if c[:2] == ["issue", "close"])
    assert close[close.index("--reason") + 1] == "completed"
    assert close[close.index("--repo") + 1] == REPO
    comment = close[close.index("--comment") + 1]
    assert comment == (
        "Closed by #220 (merged into dev as 0123456). Ships in the next release from master."
    )
    assert "#9: closed." in capsys.readouterr().out


@pytest.mark.parametrize(
    "body",
    [
        "close #7",
        "closes #7",
        "closed #7",
        "fix #7",
        "fixes #7",
        "fixed #7",
        "resolve #7",
        "resolves #7",
        "resolved #7",
        "CLOSES #7",
        "Fixes: #7",
        "Resolves:#7",
        "Closes\t#7",
        "Closes Reid-n0rc/n1mm-scope-bridge#7",
        "closes reid-n0rc/N1MM-scope-bridge#7",
        "Some text. Fixes #7.",
        "(fixes #7)",
        "- Closes #7\n",
    ],
)
def test_closing_keyword_variants(body: str) -> None:
    assert cli.closing_issues(body, REPO) == [7]


@pytest.mark.parametrize(
    "body",
    [
        "See #7",
        "Related to #7",
        "prefixes #7",
        "pre-fixes #7",
        "closesx #7",
        "closes 7",
        "closes #",
        "closes #7a",
        "closes #7-1",
        "closes # 7",
        "Closes someone/other-repo#7",
        "Closes Reid-n0rc/other-repo#7",
        "closes #0",
        "",
    ],
)
def test_non_closing_text_matches_nothing(body: str) -> None:
    assert cli.closing_issues(body, REPO) == []


def test_several_references_are_ordered_and_deduplicated() -> None:
    body = "Closes #3\nFixes #4\nresolves Reid-n0rc/n1mm-scope-bridge#3\nCloses other/repo#5"
    assert cli.closing_issues(body, REPO) == [3, 4]


def test_several_open_issues_are_all_closed() -> None:
    gh = FakeGh(pr(body="Closes #3, fixes #4, closes #3"))
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == [3, 4]


def test_cross_repo_reference_is_never_looked_up() -> None:
    gh = FakeGh(pr(body="Closes someone/else#5"))
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == []
    assert len(gh.calls) == 1


def test_already_closed_issue_is_skipped(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(body="Closes #3 and closes #4"), states={3: "closed"})
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == [4]
    assert "#3: not open, skipped." in capsys.readouterr().out


def test_pull_request_number_is_never_closed(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(body="Closes #3\nCloses #4"), pulls=[3])
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == [4]
    assert "#3: a pull request, skipped." in capsys.readouterr().out


def test_cap_is_allowed_exactly() -> None:
    body = " ".join(f"closes #{n}" for n in range(1, cli.MAX_ISSUES + 1))
    gh = FakeGh(pr(body=body))
    assert cli.main(["100"], gh) == 0
    assert gh.closed() == list(range(1, cli.MAX_ISSUES + 1))


def test_over_the_cap_fails_and_closes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    body = " ".join(f"closes #{n}" for n in range(1, cli.MAX_ISSUES + 2))
    gh = FakeGh(pr(body=body))
    assert cli.main(["100"], gh) == 1
    assert gh.closed() == []
    assert len(gh.calls) == 1
    assert "more than 10; closing none" in capsys.readouterr().err


@pytest.mark.parametrize("body", ["No links here.", "", None], ids=["text", "empty", "null"])
def test_no_linked_issues_closes_nothing(
    body: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(pr(body=body))
    assert cli.main(["1", REPO], gh) == 0
    assert gh.closed() == []
    assert "links no issues" in capsys.readouterr().out


@pytest.mark.parametrize("merged", [False, None, "true", 1], ids=["false", "null", "str", "int"])
def test_unmerged_pr_closes_nothing(merged: Any, capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(merged=merged))
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == []
    assert len(gh.calls) == 1
    assert "not merged" in capsys.readouterr().out


@pytest.mark.parametrize(
    "base", [{"ref": "master"}, {"ref": "Dev"}, {}, None], ids=["master", "case", "no-ref", "null"]
)
def test_pr_into_another_branch_closes_nothing(
    base: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(pr(base=base))
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == []
    assert "not based on 'dev'" in capsys.readouterr().out


@pytest.mark.parametrize("sha", [None, ""], ids=["null", "empty"])
def test_missing_merge_commit_is_an_error(
    sha: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(pr(merge_commit_sha=sha))
    assert cli.main(["1"], gh) == 1
    assert gh.closed() == []
    assert "no merge commit" in capsys.readouterr().err


def test_malformed_body_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(body=["Closes #9"]))
    assert cli.main(["1"], gh) == 1
    assert gh.closed() == []
    assert "malformed body" in capsys.readouterr().err


@pytest.mark.parametrize("payload", ["[]", "null", "42"], ids=["list", "null", "number"])
def test_malformed_pr_payload_is_an_error(payload: str) -> None:
    assert cli.main(["1"], lambda args: payload) == 1


def test_gh_failure_exits_non_zero_with_message(capsys: pytest.CaptureFixture[str]) -> None:
    def failing(args: Sequence[str]) -> str:
        raise RuntimeError("gh api failed: HTTP 502")

    assert cli.main(["12"], failing) == 1
    err = capsys.readouterr().err
    assert "could not close the issues linked by PR #12" in err
    assert "HTTP 502" in err


def test_issue_lookup_failure_stops_before_closing(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(body="Closes #3"))
    calls: list[list[str]] = []

    def flaky(args: Sequence[str]) -> str:
        calls.append(list(args))
        if "issues" in args[1]:
            raise RuntimeError("gh api failed: HTTP 404")
        return gh(args)

    assert cli.main(["1"], flaky) == 1
    assert not any(c[:2] == ["issue", "close"] for c in calls)
    assert "HTTP 404" in capsys.readouterr().err


def test_malformed_issue_payload_is_an_error() -> None:
    gh = FakeGh(pr(body="Closes #3"))

    def odd(args: Sequence[str]) -> str:
        return "[]" if "issues" in args[1] else gh(args)

    assert cli.main(["1"], odd) == 1


def test_close_failure_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr())

    def refuse(args: Sequence[str]) -> str:
        if args[:2] == ["issue", "close"]:
            raise RuntimeError("gh issue failed: HTTP 403")
        return gh(args)

    assert cli.main(["1"], refuse) == 1
    assert "HTTP 403" in capsys.readouterr().err


def test_invalid_json_from_gh_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["1"], lambda args: "not json") == 1
    assert "invalid JSON" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [[], ["abc"], ["1", REPO, "extra"], ["1", "no-slash"], ["1", "a/b; rm -rf /"]],
    ids=["none", "nan", "3", "bad-repo", "injection"],
)
def test_bad_arguments_print_usage(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr())
    assert cli.main(argv, gh) == 2
    assert gh.calls == []
    assert "usage:" in capsys.readouterr().err


def test_logs_contain_only_numbers(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(body="Closes #3 secret-text-here", title="private title"))
    assert cli.main(["1"], gh) == 0
    out = capsys.readouterr().out
    assert "secret" not in out
    assert "private" not in out


def test_fake_rejects_unexpected_calls() -> None:
    with pytest.raises(AssertionError):
        FakeGh(pr())(["api", "x"])
