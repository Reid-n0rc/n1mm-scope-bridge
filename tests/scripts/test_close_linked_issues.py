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
MERGED_AT = "2026-10-16T15:17:12Z"
BEFORE = "2026-10-16T15:10:00Z"
AFTER = "2026-10-16T15:20:00Z"


def pr(**kw: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "merged": True,
        "merged_at": MERGED_AT,
        "base": {"ref": "dev"},
        "head": {"repo": {"full_name": REPO}},
        "author_association": "OWNER",
        "merge_commit_sha": SHA,
        "body": "Closes #9\n\nDetails.",
    }
    data.update(kw)
    return data


def xref(pr_number: int, when: str = BEFORE, repo: str = REPO, is_pr: bool = True) -> Any:
    source: dict[str, Any] = {"number": pr_number, "repository": {"full_name": repo}}
    if is_pr:
        source["pull_request"] = {"url": "x"}
    return {"event": "cross-referenced", "created_at": when, "source": {"issue": source}}


class FakeGh:
    """A fake ``gh`` serving one PR (#1 unless the test says otherwise) and its issues.

    Issues are open, approved, assigned, and referenced by the PR before the
    merge, unless overridden.
    """

    def __init__(
        self,
        the_pr: dict[str, Any],
        issues: dict[int, dict[str, Any]] | None = None,
        timelines: dict[int, list[Any]] | None = None,
        edited: str | None = BEFORE,
    ) -> None:
        self.the_pr = the_pr
        self.issues = issues or {}
        self.timelines = timelines or {}
        self.edited = edited
        self.pr_number = 1
        self.calls: list[list[str]] = []

    def issue(self, number: int) -> dict[str, Any]:
        info: dict[str, Any] = {
            "number": number,
            "state": "open",
            "labels": [{"name": "bug"}, {"name": "plan-approved"}],
            "assignees": [{"login": "Reid-n0rc"}],
        }
        info.update(self.issues.get(number, {}))
        return info

    def __call__(self, args: Sequence[str]) -> str:
        self.calls.append(list(args))
        path = args[1] if len(args) > 1 else ""
        if args[0] == "api" and path.startswith(f"repos/{REPO}/pulls/"):
            self.pr_number = int(path.rsplit("/", 1)[1])
            return json.dumps(self.the_pr)
        if args[0] == "api" and path == "graphql":
            pull = {"lastEditedAt": self.edited}
            return json.dumps({"data": {"repository": {"pullRequest": pull}}})
        if args[0] == "api" and "/timeline?" in path:
            number = int(path.split("/issues/")[1].split("/")[0])
            page = int(path.rsplit("page=", 1)[1])
            events = self.timelines.get(number, [{"event": "labeled"}, xref(self.pr_number)])
            return json.dumps(events[(page - 1) * 100 : page * 100])
        if args[0] == "api" and path.startswith(f"repos/{REPO}/issues/"):
            return json.dumps(self.issue(int(path.rsplit("/", 1)[1])))
        if args[:2] == ["issue", "close"]:
            return ""
        raise AssertionError(f"unexpected gh call {args}")

    def closed(self) -> list[int]:
        return [int(c[2]) for c in self.calls if c[:2] == ["issue", "close"]]


def run(gh: FakeGh, capsys: pytest.CaptureFixture[str], code: int = 0) -> str:
    assert cli.main(["1"], gh) == code
    captured = capsys.readouterr()
    return captured.out + captured.err


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


def test_graphql_query_names_the_pr() -> None:
    gh = FakeGh(pr())
    assert cli.main(["7"], gh) == 0
    query = next(c for c in gh.calls if c[:2] == ["api", "graphql"])
    assert "number=7" in query
    assert "owner=Reid-n0rc" in query
    assert "name=n1mm-scope-bridge" in query


# --- parser ---------------------------------------------------------------


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
        "Closes Reid-n0rc/n1mm-scope-bridge#7",
        "closes reid-n0rc/N1MM-scope-bridge#7",
        "Some text. Fixes #7.",
        "(fixes #7)",
        "- Closes #7\n",
        "**Closes #7**",
        "Closes #7\r\nmore",
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
        "\u00e9fixes #7",
        "closesx #7",
        "closes 7",
        "closes #",
        "closes #7a",
        "closes #7-1",
        "closes #7\u00e9",
        "closes # 7",
        "closes  #7",
        "closes\t#7",
        "Resolves:#7",
        "closes \uff037",
        "closes #\uff17",
        "clo\u017fes #7",
        "Closes someone/other-repo#7",
        "Closes Reid-n0rc/other-repo#7",
        "closes #0",
        "",
    ],
)
def test_non_closing_text_matches_nothing(body: str) -> None:
    assert cli.closing_issues(body, REPO) == []


@pytest.mark.parametrize(
    "body",
    [
        "```\nCloses #7\n```",
        "~~~md\nCloses #7\n~~~",
        "````\n```\nCloses #7\n```\n````",
        "```\nCloses #7",
        "    Closes #7",
        "\tCloses #7",
        "Use `Closes #7` to link.",
        "Use ``Closes #7 ` here`` to link.",
        "<!-- Closes #7 -->",
        "<!--\nCloses #7\n-->",
        "<!-- Closes #7",
        "> Closes #7",
        "   > Closes #7",
        "[Closes #7](https://example.com)",
        "[Closes #7][ref]",
        "![Closes #7](img.png)",
        "<https://example.com/closes #7>",
        "https://example.com/?q=closes #7",
        "www.example.com/closes #7",
    ],
    ids=[
        "fence",
        "tilde-fence",
        "nested-fence",
        "unclosed-fence",
        "indented",
        "tab-indented",
        "code-span",
        "double-tick-span",
        "comment",
        "multiline-comment",
        "unclosed-comment",
        "blockquote",
        "indented-blockquote",
        "link-text",
        "reference-link",
        "image",
        "autolink",
        "bare-url",
        "www-url",
    ],
)
def test_references_in_ignored_constructs_match_nothing(body: str) -> None:
    assert cli.closing_issues(body, REPO) == []


def test_text_around_ignored_constructs_still_counts() -> None:
    body = "Closes #3\n\n```\nCloses #4\n```\n\n<!-- Closes #5 -->\nFixes #6 and `x`"
    assert cli.closing_issues(body, REPO) == [3, 6]


def test_several_references_are_ordered_and_deduplicated() -> None:
    body = "Closes #3\nFixes #4\nresolves Reid-n0rc/n1mm-scope-bridge#3\nCloses other/repo#5"
    assert cli.closing_issues(body, REPO) == [3, 4]


# --- flow -----------------------------------------------------------------


def test_several_open_issues_are_all_closed() -> None:
    gh = FakeGh(pr(body="Closes #3, fixes #4, closes #3"))
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == [3, 4]


def test_cross_repo_reference_is_never_looked_up() -> None:
    gh = FakeGh(pr(body="Closes someone/else#5"))
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == []
    assert len(gh.calls) == 1


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"state": "closed"}, "not open"),
        ({"pull_request": {"url": "x"}}, "a pull request"),
        ({"labels": [{"name": "plan-needs-approval"}]}, "no plan-approved"),
        ({"labels": None}, "no plan-approved"),
        ({"assignees": []}, "no assignee"),
    ],
    ids=["closed", "pull-request", "unapproved", "no-labels", "unassigned"],
)
def test_ineligible_issue_is_skipped(
    override: dict[str, Any], reason: str, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(pr(body="Closes #3 and closes #4"), issues={3: override})
    out = run(gh, capsys)
    assert gh.closed() == [4]
    assert f"#3: {reason}, skipped." in out


@pytest.mark.parametrize(
    "events",
    [
        [],
        [xref(1, when=AFTER)],
        [xref(2)],
        [xref(1, is_pr=False)],
        [xref(1, repo="someone/else")],
        [{"event": "connected", "created_at": BEFORE}],
        [{"event": "cross-referenced", "created_at": BEFORE, "source": None}],
    ],
    ids=["none", "after-merge", "other-pr", "from-issue", "other-repo", "connected", "no-src"],
)
def test_issue_not_referenced_before_merge_is_skipped(
    events: list[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(pr(body="Closes #3"), timelines={3: events})
    out = run(gh, capsys)
    assert gh.closed() == []
    assert "#3: not referenced before the merge, skipped." in out


def test_reference_on_a_later_timeline_page_counts() -> None:
    events = [{"event": "labeled"}] * 100 + [xref(1)]
    gh = FakeGh(pr(body="Closes #3"), timelines={3: events})
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == [3]


def test_exactly_full_last_page_ends_cleanly() -> None:
    gh = FakeGh(pr(body="Closes #3"), timelines={3: [{"event": "labeled"}] * 100})
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == []


def test_timeline_over_the_page_cap_fails(capsys: pytest.CaptureFixture[str]) -> None:
    events = [{"event": "labeled"}] * (100 * cli.MAX_TIMELINE_PAGES + 1)
    gh = FakeGh(pr(body="Closes #3"), timelines={3: events})
    assert "longer than 10 pages" in run(gh, capsys, code=1)
    assert gh.closed() == []


def test_malformed_timeline_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(body="Closes #3"))

    def odd(args: Sequence[str]) -> str:
        return "{}" if "/timeline?" in args[1] else gh(args)

    assert cli.main(["1"], odd) == 1
    assert "malformed timeline" in capsys.readouterr().err


def test_bad_event_time_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(body="Closes #3"), timelines={3: [xref(1, when="yesterday")]})
    assert "event time is malformed" in run(gh, capsys, code=1)


@pytest.mark.parametrize("association", ["CONTRIBUTOR", "NONE", "FIRST_TIME_CONTRIBUTOR", None])
def test_untrusted_author_closes_nothing(
    association: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(pr(author_association=association))
    assert "not a collaborator" in run(gh, capsys)
    assert gh.closed() == []
    assert len(gh.calls) == 1


@pytest.mark.parametrize("head", [{"repo": {"full_name": "fork/n1mm"}}, {"repo": None}, None])
def test_fork_pr_closes_nothing(head: Any, capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(head=head))
    assert "from a fork" in run(gh, capsys)
    assert gh.closed() == []
    assert len(gh.calls) == 1


def test_body_edited_after_merge_closes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(), edited=AFTER)
    assert "edited after the merge; closing none" in run(gh, capsys, code=1)
    assert gh.closed() == []


@pytest.mark.parametrize("edited", [None, MERGED_AT], ids=["never", "at-merge"])
def test_body_not_edited_after_merge_proceeds(edited: str | None) -> None:
    gh = FakeGh(pr(), edited=edited)
    assert cli.main(["1"], gh) == 0
    assert gh.closed() == [9]


def test_malformed_graphql_response_is_an_error() -> None:
    gh = FakeGh(pr())

    def odd(args: Sequence[str]) -> str:
        return '{"data": null}' if args[1] == "graphql" else gh(args)

    assert cli.main(["1"], odd) == 1
    assert gh.closed() == []


@pytest.mark.parametrize("merged_at", [None, "not a time"], ids=["missing", "malformed"])
def test_bad_merged_at_is_an_error(merged_at: str | None) -> None:
    gh = FakeGh(pr(merged_at=merged_at))
    assert cli.main(["1"], gh) == 1
    assert gh.closed() == []


def test_cap_is_allowed_exactly() -> None:
    body = " ".join(f"closes #{n}" for n in range(1, cli.MAX_ISSUES + 1))
    gh = FakeGh(pr(body=body))
    assert cli.main(["100"], gh) == 0
    assert gh.closed() == list(range(1, cli.MAX_ISSUES + 1))


def test_over_the_cap_fails_and_closes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    body = " ".join(f"closes #{n}" for n in range(1, cli.MAX_ISSUES + 2))
    gh = FakeGh(pr(body=body))
    assert "more than 10; closing none" in run(gh, capsys, code=1)
    assert gh.closed() == []
    assert len(gh.calls) == 1


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
    assert "not merged" in run(gh, capsys)
    assert gh.closed() == []
    assert len(gh.calls) == 1


@pytest.mark.parametrize(
    "base", [{"ref": "master"}, {"ref": "Dev"}, {}, None], ids=["master", "case", "no-ref", "null"]
)
def test_pr_into_another_branch_closes_nothing(
    base: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(pr(base=base))
    assert "not based on 'dev'" in run(gh, capsys)
    assert gh.closed() == []


@pytest.mark.parametrize("sha", [None, ""], ids=["null", "empty"])
def test_missing_merge_commit_is_an_error(
    sha: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(pr(merge_commit_sha=sha))
    assert "no merge commit" in run(gh, capsys, code=1)
    assert gh.closed() == []


def test_malformed_body_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(body=["Closes #9"]))
    assert "malformed body" in run(gh, capsys, code=1)
    assert gh.closed() == []


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


@pytest.mark.parametrize("failing_call", ["graphql", "/timeline?", "/issues/3"])
def test_lookup_failure_stops_before_closing(
    failing_call: str, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(pr(body="Closes #3"))

    def flaky(args: Sequence[str]) -> str:
        if args[0] == "api" and failing_call in args[1]:
            raise RuntimeError("gh api failed: HTTP 404")
        return gh(args)

    assert cli.main(["1"], flaky) == 1
    assert gh.closed() == []
    assert "HTTP 404" in capsys.readouterr().err


def test_malformed_issue_payload_is_an_error() -> None:
    gh = FakeGh(pr(body="Closes #3"))

    def odd(args: Sequence[str]) -> str:
        return "[]" if args[1].endswith("/issues/3") else gh(args)

    assert cli.main(["1"], odd) == 1
    assert gh.closed() == []


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
    [
        [],
        ["abc"],
        ["\u0661"],
        ["1", REPO, "extra"],
        ["1", "no-slash"],
        ["1", "a/b; rm -rf /"],
        ["1", "\u00e4/b"],
    ],
    ids=["none", "nan", "arabic-digit", "3", "bad-repo", "injection", "non-ascii"],
)
def test_bad_arguments_print_usage(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr())
    assert cli.main(argv, gh) == 2
    assert gh.calls == []
    assert "usage:" in capsys.readouterr().err


def test_logs_contain_only_numbers(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(pr(body="Closes #3 secret-text-here", title="private title"))
    out = run(gh, capsys)
    assert "secret" not in out
    assert "private" not in out


def test_fake_rejects_unexpected_calls() -> None:
    with pytest.raises(AssertionError):
        FakeGh(pr())(["api", "x"])
