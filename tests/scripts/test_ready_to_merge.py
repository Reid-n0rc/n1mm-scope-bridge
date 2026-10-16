# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
import ready_to_merge as rtm
from check_issue_policy import IssueInfo

APPROVED = IssueInfo(labels=("plan-approved",), assignees=("Reid-n0rc",))


def run(
    name: str, conclusion: str | None = "success", status: str = "completed", id_: int = 1
) -> dict[str, Any]:
    return {"name": name, "status": status, "conclusion": conclusion, "id": id_}


def pr(**kw: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "number": 5,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "headRefOid": "abc123",
        "body": "Closes #9",
        "baseRefName": "dev",
        "headRefName": "issue-9-x",
        "isCrossRepository": False,
    }
    data.update(kw)
    return data


def conn(items: list[dict[str, Any]], total: int | None = None, more: bool = False) -> Any:
    return {
        "totalCount": len(items) if total is None else total,
        "pageInfo": {"hasNextPage": more},
        "nodes": items,
    }


def node(**kw: Any) -> dict[str, Any]:
    """A GraphQL ISSUE_QUERY issue node for #9 of o/r; keyword arguments override fields."""
    data: dict[str, Any] = {
        "__typename": "Issue",
        "number": 9,
        "state": "OPEN",
        "repository": {"nameWithOwner": "o/r"},
        "labels": conn([{"name": "plan-approved"}]),
        "assignees": conn([{"login": "Reid-n0rc"}]),
    }
    data.update(kw)
    return data


def graphql(the_node: Any) -> dict[str, Any]:
    return {"data": {"repository": {"issueOrPullRequest": the_node}}}


def fake_gh(
    *,
    the_pr: dict[str, Any] | None = None,
    runs: list[dict[str, Any]] | None = None,
    statuses: list[dict[str, Any]] | None = None,
    code: list[dict[str, Any]] | None = None,
    leaks: list[int] | None = None,
    issue: dict[str, Any] | None = None,
    missing_issue: bool = False,
    response: Any = None,
    calls: list[Sequence[str]] | None = None,
) -> rtm.Gh:
    def gh(args: Sequence[str]) -> Any:
        if calls is not None:
            calls.append(args)
        if args[0] == "pr":
            return the_pr or pr()
        path = args[1]
        if path == "graphql":
            if missing_issue:
                raise RuntimeError("gh api graphql failed: HTTP 502")
            number = int(args[-1].removeprefix("number="))
            owner, name = args[5].removeprefix("owner="), args[7].removeprefix("name=")
            repo = {"nameWithOwner": f"{owner}/{name}"}
            default = node(number=number, repository=repo)
            return response if response is not None else graphql(issue or default)
        if "/check-runs" in path:
            return {"check_runs": runs if runs is not None else [run("Lint and type check")]}
        if path.endswith("/status"):
            return {"statuses": statuses or []}
        if "code-scanning" in path:
            return code or []
        if "secret-scanning" in path:
            assert args[-2:] == ["--jq", rtm.LEAK_ALERT_JQ]  # only numbers reach the script
            return leaks or []
        raise AssertionError(f"unexpected gh call {args}")

    return gh


def test_ready_pr_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert rtm.main(["5"], gh=fake_gh()) == 0
    assert "READY: PR #5" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("runs", "message"),
    [
        ([run("CodeQL", "failure")], "check 'CodeQL' concluded failure"),
        ([run("Test", None, status="in_progress")], "check 'Test' is in_progress"),
        ([run("Test", "cancelled")], "concluded cancelled"),
        ([run("Test", "action_required")], "concluded action_required"),
        (
            [run("Dependency review", "failure")],
            "dependency review 'Dependency review' concluded failure",
        ),
        ([], "no checks have reported"),
    ],
)
def test_check_failures(runs: list[dict[str, Any]], message: str) -> None:
    assert any(message in p for p in rtm.evaluate(5, "o/r", fake_gh(runs=runs)))


def test_skipped_and_neutral_checks_are_fine() -> None:
    runs = [run("A", "skipped"), run("B", "neutral"), run("C", "success")]
    assert rtm.evaluate(5, "o/r", fake_gh(runs=runs)) == []


def test_latest_rerun_wins() -> None:
    runs = [run("CodeQL", "failure", id_=1), run("CodeQL", "success", id_=2)]
    assert rtm.evaluate(5, "o/r", fake_gh(runs=runs)) == []
    runs = [run("CodeQL", "success", id_=3), run("CodeQL", "failure", id_=4)]
    assert rtm.evaluate(5, "o/r", fake_gh(runs=runs)) != []


def test_commit_status_failure() -> None:
    problems = rtm.evaluate(
        5, "o/r", fake_gh(statuses=[{"context": "codecov/patch", "state": "failure"}])
    )
    assert problems == ["status 'codecov/patch' is failure"]


def test_open_code_scanning_alert_blocks() -> None:
    alert = {
        "number": 26,
        "rule": {"id": "py/side-effect-in-assert", "severity": "error"},
        "most_recent_instance": {"location": {"path": "tests/test_x.py", "start_line": 3}},
    }
    (problem,) = rtm.evaluate(5, "o/r", fake_gh(code=[alert]))
    assert "#26 py/side-effect-in-assert (error) at tests/test_x.py:3" in problem
    assert "written justification" in problem


def test_security_severity_preferred() -> None:
    alert = {
        "number": 1,
        "rule": {"id": "py/x", "severity": "warning", "security_severity_level": "high"},
    }
    assert "(high)" in rtm.code_scanning_problems([alert])[0]


def test_open_leak_alert_blocks() -> None:
    problems = rtm.evaluate(5, "o/r", fake_gh(leaks=[2]))
    assert problems == [
        "open secret-scanning alert #2: revoke the leaked credential and close the alert "
        "(repository Security tab)"
    ]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"state": "CLOSED"}, "PR is closed"),
        ({"isDraft": True}, "draft"),
        ({"mergeable": "CONFLICTING"}, "merge conflicts"),
        ({"mergeable": "UNKNOWN"}, "not computed mergeability"),
        ({"body": "no link"}, "Closes #<n>"),
    ],
)
def test_pr_problems(change: dict[str, Any], message: str) -> None:
    assert any(message in p for p in rtm.evaluate(5, "o/r", fake_gh(the_pr=pr(**change))))


def test_unapproved_or_missing_issue() -> None:
    unapproved = node(labels=conn([{"name": "plan-needs-approval"}]), assignees=conn([]))
    problems = rtm.evaluate(5, "o/r", fake_gh(issue=unapproved))
    assert any("plan-approved" in p for p in problems)
    assert any("not assigned" in p for p in problems)
    assert any("not an issue" in p for p in rtm.evaluate(5, "o/r", fake_gh(missing_issue=True)))


def test_issue_is_read_through_graphql_for_this_repo() -> None:
    calls: list[Sequence[str]] = []
    assert rtm.evaluate(5, "o/r", fake_gh(calls=calls)) == []
    (query,) = [c for c in calls if c[:2] == ["api", "graphql"]]
    assert list(query[2:]) == [
        "-f", query[3], "-f", "owner=o", "-f", "name=r", "-F", "number=9"
    ]  # fmt: skip
    assert any(arg.startswith("query=") and "totalCount" in arg for arg in query)
    assert not any("/issues/" in arg for c in calls for arg in c)  # no REST issue read


def blocked(gh: rtm.Gh, *messages: str) -> None:
    """The PR is NOT READY, with every message among the reasons."""
    problems = rtm.evaluate(5, "o/r", gh)
    for message in messages:
        assert any(message in p for p in problems), (message, problems)
    assert rtm.main(["5", "o/r"], gh=gh) == 1


@pytest.mark.parametrize(
    ("the_node", "messages"),
    [
        (node(state="CLOSED"), ["#9 is closed"]),
        (node(state="MERGED"), ["unexpected state"]),
        (node(labels=conn([{"name": "plan-approved"}], total=2)), ["labels", "returned 1"]),
        (node(labels=conn([{"name": "plan-approved"}], more=True)), ["labels", "incomplete"]),
        (node(assignees=conn([{"login": "Reid-n0rc"}], total=101)), ["assignees"]),
        (node(assignees=conn([{"login": "Reid-n0rc"}], more=True)), ["incomplete"]),
        (node(assignees=conn([{"login": ""}])), ["no `login`"]),
        (node(assignees=conn([{}])), ["no `login`"]),
        (node(assignees=conn([{"login": None}])), ["no `login`"]),
        (node(labels=conn([{"name": ""}])), ["no `name`"]),
        (node(labels=None), ["labels are missing"]),
        (node(repository={"nameWithOwner": "other/repo"}), ["belongs to 'other/repo'"]),
        (node(repository=None), ["no repository"]),
        (node(number=10), ["issue number 10"]),
        ({"__typename": "PullRequest"}, ["#9 is not an issue"]),
        ({"__typename": "Discussion"}, ["unexpected type"]),
        (None, ["#9 is not an issue"]),
    ],
)
def test_untrusted_or_failing_issue_is_not_ready(the_node: Any, messages: list[str]) -> None:
    blocked(
        fake_gh(issue=the_node) if the_node is not None else fake_gh(response=graphql(None)),
        *messages,
    )


@pytest.mark.parametrize(
    "response",
    [
        {"errors": [{"message": "Something went wrong"}]},
        {"data": None},
        {"data": {"repository": None}},
        [],
        "",
    ],
)
def test_graphql_errors_are_not_ready(response: Any) -> None:
    blocked(fake_gh(response=response), "#9 could not be verified", "#9 is not an issue")


def test_api_error_is_not_ready(capsys: pytest.CaptureFixture[str]) -> None:
    blocked(fake_gh(missing_issue=True), "#9 could not be verified: gh api graphql failed")
    assert "NOT READY: PR #5" in capsys.readouterr().out


def test_every_linked_issue_must_pass() -> None:
    def gh(args: Sequence[str]) -> Any:
        if args[:2] == ["api", "graphql"]:
            number = int(args[-1].removeprefix("number="))
            state = "OPEN" if number == 9 else "CLOSED"
            return graphql(node(number=number, state=state))
        return fake_gh(the_pr=pr(body="Closes #9\nFixes #11"))(args)

    blocked(gh, "#11 is closed")
    assert not any("#9" in p for p in rtm.evaluate(5, "o/r", gh))


def test_cross_repo_and_url_references_do_not_count() -> None:
    for body in ("Closes other/repo#9", "Closes https://github.com/o/r/issues/9", "Closes #\u0669"):
        blocked(fake_gh(the_pr=pr(body=body)), "Closes #<n>")


@pytest.mark.parametrize(
    "the_pr",
    [pr(number=6), pr(body=["Closes #9"]), [], None],
)
def test_wrong_or_malformed_pr_is_not_ready(
    the_pr: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    def gh(args: Sequence[str]) -> Any:
        return the_pr if args[0] == "pr" else fake_gh()(args)

    assert rtm.main(["5"], gh=gh) == 1
    assert "NOT READY: could not evaluate PR #5" in capsys.readouterr().out


def test_release_pr_needs_no_issue() -> None:
    release = pr(body="Release v0.1.0", baseRefName="master", headRefName="dev")
    assert rtm.evaluate(5, "o/r", fake_gh(the_pr=release)) == []
    calls: list[Sequence[str]] = []
    with_link = pr(body="Release, closes #9", baseRefName="master", headRefName="dev")
    assert rtm.evaluate(5, "o/r", fake_gh(the_pr=with_link, missing_issue=True, calls=calls)) == []
    assert not any(c[:2] == ["api", "graphql"] for c in calls)


@pytest.mark.parametrize("cross", [True, None])
def test_fork_dev_branch_is_not_a_release_pr(cross: bool | None) -> None:
    fork = pr(body="Release", baseRefName="master", headRefName="dev", isCrossRepository=cross)
    blocked(fake_gh(the_pr=fork), "Closes #<n>")


def test_main_reports_all_reasons_and_usage(capsys: pytest.CaptureFixture[str]) -> None:
    gh = fake_gh(runs=[run("CodeQL", "failure")], the_pr=pr(mergeable="CONFLICTING"))
    assert rtm.main(["5", "o/r"], gh=gh) == 1
    out = capsys.readouterr().out
    assert out.startswith("NOT READY: PR #5")
    assert "CodeQL" in out
    assert "conflicts" in out
    assert rtm.main([], gh=gh) == 2
    assert rtm.main(["abc"], gh=gh) == 2
    for bad in (["\u0665"], ["05"], ["+5"], [" 5"], ["5", "not a repo"], ["5", "o/r", "x"]):
        assert rtm.main(bad, gh=gh) == 2


def test_main_reports_gh_errors(capsys: pytest.CaptureFixture[str]) -> None:
    def broken(args: Sequence[str]) -> Any:
        raise RuntimeError("gh: not logged in")

    assert rtm.main(["5"], gh=broken) == 1
    assert "could not evaluate" in capsys.readouterr().out

    def crashing(args: Sequence[str]) -> Any:
        raise ValueError("unexpected")

    assert rtm.main(["5"], gh=crashing) == 1
    assert "NOT READY: could not evaluate PR #5: unexpected" in capsys.readouterr().out


def test_parse_helpers_directly() -> None:
    assert rtm.latest_check_runs([]) == {}
    assert rtm.leak_alert_problems([]) == []
    assert rtm.pr_problems(pr(), {9: APPROVED}) == []


def test_copilot_review_failure_is_advisory_when_codeql_passed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = [run("CodeQL", "success"), run("github-advanced-security", "failure")]
    assert rtm.main(["5"], gh=fake_gh(runs=runs)) == 0
    out = capsys.readouterr().out
    assert "NOTE: advisory check 'github-advanced-security' concluded failure" in out
    assert "READY" in out


@pytest.mark.parametrize("codeql", [None, "failure"])
def test_copilot_review_failure_blocks_without_passing_codeql(codeql: str | None) -> None:
    runs = [run("github-advanced-security", "failure")]
    if codeql:
        runs.append(run("CodeQL", codeql))
    problems = rtm.evaluate(5, "o/r", fake_gh(runs=runs))
    assert any("github-advanced-security" in p for p in problems)


def test_advisory_does_not_hide_open_alerts() -> None:
    runs = [run("CodeQL", "success"), run("github-advanced-security", "failure")]
    alert = {"number": 7, "rule": {"id": "py/x", "severity": "error"}}
    problems = rtm.evaluate(5, "o/r", fake_gh(runs=runs, code=[alert]))
    assert len(problems) == 1
    assert "#7" in problems[0]
