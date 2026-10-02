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
    }
    data.update(kw)
    return data


def fake_gh(
    *,
    the_pr: dict[str, Any] | None = None,
    runs: list[dict[str, Any]] | None = None,
    statuses: list[dict[str, Any]] | None = None,
    code: list[dict[str, Any]] | None = None,
    secrets: list[dict[str, Any]] | None = None,
    issue: dict[str, Any] | None = None,
    missing_issue: bool = False,
) -> rtm.Gh:
    def gh(args: Sequence[str]) -> Any:
        if args[0] == "pr":
            return the_pr or pr()
        path = args[1]
        if "/check-runs" in path:
            return {"check_runs": runs if runs is not None else [run("Lint and type check")]}
        if path.endswith("/status"):
            return {"statuses": statuses or []}
        if "code-scanning" in path:
            return code or []
        if "secret-scanning" in path:
            return secrets or []
        if "/issues/" in path:
            if missing_issue:
                raise RuntimeError("HTTP 404")
            return issue or {
                "labels": [{"name": "plan-approved"}],
                "assignees": [{"login": "Reid-n0rc"}],
            }
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


def test_open_secret_alert_blocks() -> None:
    problems = rtm.evaluate(
        5, "o/r", fake_gh(secrets=[{"number": 2, "secret_type_display_name": "GitHub token"}])
    )
    assert problems == [
        "open secret-scanning alert #2 (GitHub token): revoke the secret and resolve the alert"
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
    unapproved = {"labels": [{"name": "plan-needs-approval"}], "assignees": []}
    problems = rtm.evaluate(5, "o/r", fake_gh(issue=unapproved))
    assert any("plan-approved" in p for p in problems)
    assert any("not assigned" in p for p in problems)
    assert any("not an issue" in p for p in rtm.evaluate(5, "o/r", fake_gh(missing_issue=True)))


def test_release_pr_needs_no_issue() -> None:
    release = pr(body="Release v0.1.0", baseRefName="master", headRefName="dev")
    assert rtm.evaluate(5, "o/r", fake_gh(the_pr=release)) == []


def test_main_reports_all_reasons_and_usage(capsys: pytest.CaptureFixture[str]) -> None:
    gh = fake_gh(runs=[run("CodeQL", "failure")], the_pr=pr(mergeable="CONFLICTING"))
    assert rtm.main(["5", "o/r"], gh=gh) == 1
    out = capsys.readouterr().out
    assert out.startswith("NOT READY: PR #5")
    assert "CodeQL" in out
    assert "conflicts" in out
    assert rtm.main([], gh=gh) == 2
    assert rtm.main(["abc"], gh=gh) == 2


def test_main_reports_gh_errors(capsys: pytest.CaptureFixture[str]) -> None:
    def broken(args: Sequence[str]) -> Any:
        raise RuntimeError("gh: not logged in")

    assert rtm.main(["5"], gh=broken) == 1
    assert "could not evaluate" in capsys.readouterr().out


def test_parse_helpers_directly() -> None:
    assert rtm.latest_check_runs([]) == {}
    assert rtm.secret_scanning_problems([]) == []
    assert rtm.pr_problems(pr(), {9: APPROVED}) == []
