# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from typing import Any

import pytest
from check_issue_policy import (
    IssueInfo,
    Review,
    bot_label_actor,
    bot_pr_problems,
    current_pr,
    is_bot_pr,
    is_release_pr,
    linked_issues,
    parse_issue,
    parse_reviews,
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


# --- current PR (stale payloads, workflow_dispatch) ------------------------------------


def test_current_pr_prefers_fresh_api_copy() -> None:
    event = {"pull_request": {"number": 7, "body": "old body"}}
    fresh = {"number": 7, "body": "Closes #1", "base": {"ref": "dev"}, "head": {"ref": "x"}}
    assert current_pr(event, None, lambda n: fresh) is fresh
    assert current_pr(event, None, None) == event["pull_request"]


def test_current_pr_by_number_for_dispatch() -> None:
    seen: list[int] = []

    def fetch(n: int) -> dict[str, Any]:
        seen.append(n)
        return {"number": n, "body": ""}

    assert current_pr({}, 12, fetch) == {"number": 12, "body": ""}
    assert seen == [12]
    assert current_pr({}, None, fetch) is None


def test_run_uses_edited_body() -> None:
    out: list[str] = []
    event = {"pull_request": {"number": 3, "body": "no link yet"}}
    fresh = {"number": 3, "body": "Closes #1", "base": {"ref": "dev"}, "head": {"ref": "a"}}
    assert run(event, lambda n: OK, out.append, fetch_pull=lambda n: fresh) == 0
    assert out == ["Issue policy OK for #1."]


def test_run_without_any_pr_fails() -> None:
    out: list[str] = []
    assert run({}, lambda n: OK, out.append) == 1
    assert "PR_NUMBER" in out[0]


# --- bots (#224): no self-approved plans, no merge without the maintainer -------------

HEAD = "abc1234def"
BOT_PR = {
    "number": 9,
    "body": "Closes #1",
    "user": {"login": "claude[bot]", "type": "Bot"},
    "base": {"ref": "dev"},
    "head": {"ref": "issue-1-x", "sha": HEAD},
}


def _labeled(login: str, kind: str, label: str = "plan-approved") -> dict[str, Any]:
    return {"event": "labeled", "label": {"name": label}, "actor": {"login": login, "type": kind}}


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([_labeled("Reid-n0rc", "User")], None),
        ([_labeled("claude[bot]", "Bot")], "claude[bot]"),
        ([_labeled("github-actions[bot]", "Bot")], None),
        ([_labeled("claude[bot]", "Bot"), _labeled("Reid-n0rc", "User")], None),
        ([_labeled("Reid-n0rc", "User"), _labeled("claude[bot]", "Bot")], "claude[bot]"),
        ([_labeled("claude[bot]", "Bot", label="lane:site")], None),
        ([{"event": "assigned", "actor": {"login": "x[bot]", "type": "Bot"}}], None),
        ([{"event": "labeled", "label": None, "actor": None}], None),
        ([], None),
    ],
    ids=[
        "maintainer",
        "untrusted-bot",
        "autofix-conform-bot",
        "bot-then-maintainer",
        "maintainer-then-bot",
        "other-label",
        "other-event",
        "missing-fields",
        "no-events",
    ],
)
def test_bot_label_actor(events: list[dict[str, Any]], expected: str | None) -> None:
    assert bot_label_actor(events) == expected


def test_policy_rejects_plan_approved_by_a_bot() -> None:
    issue = IssueInfo(("plan-approved",), ("Reid-n0rc",), approved_by_bot="claude[bot]")
    assert policy_problems([1], {1: issue}) == [
        "#1: `plan-approved` was added by 'claude[bot]'. Only the maintainer approves plans."
    ]


def test_parse_reviews() -> None:
    data: list[dict[str, Any]] = [
        {"user": {"login": "a"}, "state": "APPROVED", "commit_id": "c"},
        {"user": None},
    ]
    assert parse_reviews(data) == [Review("a", "APPROVED", "c"), Review("", "", "")]


def test_human_pr_needs_no_review() -> None:
    human = {**BOT_PR, "user": {"login": "Reid-n0rc", "type": "User"}}
    assert not is_bot_pr(human)
    assert not is_bot_pr({})
    assert bot_pr_problems(human, []) == []


@pytest.mark.parametrize(
    ("reviews", "ok"),
    [
        ([], False),
        ([Review("Reid-n0rc", "APPROVED", HEAD)], True),
        ([Review("Reid-n0rc", "APPROVED", "stale00")], False),
        ([Review("someone", "APPROVED", HEAD)], False),
        ([Review("Reid-n0rc", "APPROVED", HEAD), Review("Reid-n0rc", "COMMENTED", HEAD)], True),
        ([Review("Reid-n0rc", "APPROVED", HEAD), Review("Reid-n0rc", "DISMISSED", HEAD)], False),
        (
            [Review("Reid-n0rc", "CHANGES_REQUESTED", HEAD), Review("Reid-n0rc", "APPROVED", HEAD)],
            True,
        ),
    ],
    ids=[
        "no-review",
        "approved-head",
        "approved-stale-commit",
        "non-codeowner",
        "comment-after-approval",
        "dismissed",
        "approved-after-changes",
    ],
)
def test_bot_pr_needs_maintainer_approval_on_head(reviews: list[Review], ok: bool) -> None:
    problems = bot_pr_problems(BOT_PR, reviews)
    assert (problems == []) is ok
    if not ok:
        assert problems[0].startswith("PR by 'claude[bot]' needs an approving review")
        assert "(abc1234)" in problems[0]


def test_bot_pr_without_head_sha_fails() -> None:
    pr = {**BOT_PR, "head": {}}
    assert bot_pr_problems(pr, [Review("Reid-n0rc", "APPROVED", "")]) != []


def test_run_bot_pr_checks_reviews() -> None:
    out: list[str] = []
    seen: list[int] = []

    def reviews(n: int) -> list[Review]:
        seen.append(n)
        return [Review("Reid-n0rc", "APPROVED", HEAD)]

    event = {"pull_request": BOT_PR}
    assert run(event, lambda n: OK, out.append, fetch_reviews=reviews) == 0
    assert seen == [9]
    out.clear()
    assert run(event, lambda n: OK, out.append, fetch_reviews=lambda n: []) == 1
    assert "approving review" in out[0]
    out.clear()
    assert run(event, lambda n: OK, out.append) == 1
