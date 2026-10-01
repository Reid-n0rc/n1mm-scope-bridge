# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from typing import Any

import pytest
from check_issue_policy import (
    IssueInfo,
    is_release_pr,
    linked_issues,
    parse_issue,
    policy_problems,
    run,
)

OK = IssueInfo(labels=("plan-approved",), assignees=("Reid-n0rc",))


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Closes #12", [12]),
        ("fixes #3 and resolves #4", [3, 4]),
        ("CLOSED #7\nfixed #7", [7]),
        ("Closes #", []),
        ("see #5", []),
        ("", []),
        (None, []),
        ("Closes#9", []),
    ],
)
def test_linked_issues(body: str | None, expected: list[int]) -> None:
    assert linked_issues(body) == expected


@pytest.mark.parametrize(
    ("pr", "expected"),
    [
        ({"base": {"ref": "master"}, "head": {"ref": "dev"}}, True),
        ({"base": {"ref": "dev"}, "head": {"ref": "issue-1-x"}}, False),
        ({"base": {"ref": "master"}, "head": {"ref": "issue-1-x"}}, False),
        ({}, False),
        (None, False),
    ],
)
def test_is_release_pr(pr: dict[str, Any] | None, expected: bool) -> None:
    assert is_release_pr(pr) is expected


def test_policy_requires_a_linked_issue() -> None:
    problems = policy_problems([], {})
    assert len(problems) == 1
    assert "Closes #<n>" in problems[0]


def test_policy_ok() -> None:
    assert policy_problems([1], {1: OK}) == []


def test_policy_missing_label_and_assignee() -> None:
    problems = policy_problems([2], {2: IssueInfo(labels=("plan-needs-approval",), assignees=())})
    assert any("plan-approved" in p for p in problems)
    assert any("not assigned" in p for p in problems)


def test_policy_not_found_or_pull_request() -> None:
    pr_issue = IssueInfo(labels=("plan-approved",), assignees=("a",), is_pull_request=True)
    problems = policy_problems([3, 4], {3: None, 4: pr_issue})
    assert problems == [
        "#3 is not an issue in this repository.",
        "#4 is not an issue in this repository.",
    ]


def test_parse_issue_handles_string_and_object_labels() -> None:
    info = parse_issue(
        {
            "labels": ["bug", {"name": "plan-approved"}],
            "assignees": [{"login": "x"}],
            "pull_request": {},
        }
    )
    assert info == IssueInfo(
        labels=("bug", "plan-approved"), assignees=("x",), is_pull_request=False
    )


def test_parse_issue_handles_missing_fields() -> None:
    assert parse_issue({"labels": None, "assignees": None}) == IssueInfo((), ())


def test_run_release_pr_is_exempt() -> None:
    out: list[str] = []
    event = {"pull_request": {"base": {"ref": "master"}, "head": {"ref": "dev"}, "body": ""}}
    assert run(event, lambda n: None, out.append) == 0
    assert "not applicable" in out[0]


def test_run_passes_and_fails() -> None:
    out: list[str] = []
    event = {
        "pull_request": {"base": {"ref": "dev"}, "head": {"ref": "issue-1-x"}, "body": "Closes #1"}
    }
    assert run(event, lambda n: OK, out.append) == 0
    assert out == ["Issue policy OK for #1."]
    out.clear()
    assert run(event, lambda n: None, out.append) == 1
    assert out[0].startswith("::error::")
