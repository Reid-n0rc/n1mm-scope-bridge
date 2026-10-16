# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import pytest
from check_issue_policy import (
    IssueInfo,
    PolicyError,
    Target,
    check_pr,
    is_release_pr,
    linked_issues,
    parse_issue,
    parse_issue_node,
    parse_pr_number,
    policy_problems,
    run,
    target_pr,
)

REPO = "o/r"
SHA = "a" * 40
OK = IssueInfo(labels=("plan-approved",), assignees=("Reid-n0rc",))


def conn(values: list[str], key: str, *, total: int | None = None, more: bool = False) -> Any:
    return {
        "totalCount": len(values) if total is None else total,
        "pageInfo": {"hasNextPage": more},
        "nodes": [{key: v} for v in values],
    }


def issue_node(number: int = 1, **change: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "__typename": "Issue",
        "number": number,
        "state": "OPEN",
        "repository": {"nameWithOwner": REPO},
        "labels": conn(["plan-approved"], "name"),
        "assignees": conn(["Reid-n0rc"], "login"),
    }
    node.update(change)
    return node


def gql(node: Any) -> dict[str, Any]:
    return {"data": {"repository": {"issueOrPullRequest": node}}}


def api_pr(number: Any = 7, body: Any = "Closes #1", **change: Any) -> dict[str, Any]:
    pr: dict[str, Any] = {
        "number": number,
        "body": body,
        "base": {"ref": "dev", "repo": {"full_name": REPO}},
        "head": {"ref": "issue-1-x", "repo": {"full_name": REPO}},
    }
    pr.update(change)
    return pr


def release_pr(head_repo: Any = None) -> dict[str, Any]:
    head = {"ref": "dev", "repo": {"full_name": REPO} if head_repo is None else head_repo}
    return api_pr(body="Release v1", base={"ref": "master", "repo": {"full_name": REPO}}, head=head)


# --- linked issues from the body ------------------------------------------------------


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
        ("Closes other/repo#9", []),
        ("Closes https://github.com/other/repo/issues/9", []),
        ("Closes #\u0661", []),  # non-ASCII digit
        ("Closes #12345678901", []),  # more than 10 digits
    ],
)
def test_linked_issues(body: str | None, expected: list[int]) -> None:
    assert linked_issues(body) == expected


# --- release PRs ----------------------------------------------------------------------


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


def test_release_pr_with_repo_needs_same_repo_head() -> None:
    assert is_release_pr(release_pr(), REPO) is True
    # A fork's branch named `dev` is not a release PR.
    assert is_release_pr(release_pr({"full_name": "fork/r"}), REPO) is False
    assert is_release_pr(release_pr({}), REPO) is False
    assert is_release_pr(api_pr(base={"ref": "master"}, head={"ref": "dev"}), REPO) is False


# --- policy ---------------------------------------------------------------------------


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


def test_policy_closed_issue_does_not_count() -> None:
    closed = IssueInfo(labels=("plan-approved",), assignees=("a",), is_open=False)
    assert policy_problems([5], {5: closed}) == ["#5 is closed. Link an open issue."]


def test_policy_every_linked_issue_must_pass() -> None:
    bad = IssueInfo(labels=(), assignees=("a",))
    assert policy_problems([1, 2], {1: OK, 2: bad}) == [
        "#2 does not have the `plan-approved` label."
    ]
    assert policy_problems([1, 2], {1: OK}) == ["#2 is not an issue in this repository."]


# --- REST issue parser (used by ready_to_merge.py) ------------------------------------


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


def test_parse_issue_reads_state() -> None:
    assert parse_issue({"state": "closed", "labels": [], "assignees": []}).is_open is False
    assert parse_issue({"state": "open", "labels": [], "assignees": []}).is_open is True


@pytest.mark.parametrize(
    "data",
    [
        {"assignees": [{}]},  # no login: used to count as assigned
        {"assignees": [{"login": ""}]},
        {"assignees": [{"login": 5}]},
        {"assignees": ["Reid-n0rc"]},  # display text, not an API user object
        {"assignees": "Reid-n0rc"},
        {"labels": [{"name": 5}]},
        {"labels": [{}]},
        {"labels": [3]},
        {"labels": "plan-approved"},
        {"state": "merged"},
        {"state": None},
        [],
    ],
)
def test_parse_issue_rejects_malformed_data(data: Any) -> None:
    with pytest.raises(PolicyError):
        parse_issue(data)


def test_policy_error_is_a_runtime_error() -> None:
    # ready_to_merge.py treats RuntimeError from parse_issue as "not an issue".
    assert issubclass(PolicyError, RuntimeError)


# --- GraphQL issue parser (used by the CI check) --------------------------------------


def test_parse_issue_node_ok() -> None:
    info = parse_issue_node(gql(issue_node(1)), 1, REPO)
    assert info == IssueInfo(("plan-approved",), ("Reid-n0rc",), is_pull_request=False)


def test_parse_issue_node_not_found_and_pull_request() -> None:
    assert parse_issue_node(gql(None), 1, REPO) is None
    pr = parse_issue_node(gql({"__typename": "PullRequest", "number": 1}), 1, REPO)
    assert pr is not None
    assert pr.is_pull_request


def test_parse_issue_node_closed() -> None:
    info = parse_issue_node(gql(issue_node(state="CLOSED")), 1, REPO)
    assert info is not None
    assert info.is_open is False


BAD_NODES: list[tuple[Any, str]] = [
    (issue_node(number=2), "number"),
    (issue_node(repository={"nameWithOwner": "other/r"}), "other/r"),
    (issue_node(repository=None), "repository"),
    (issue_node(state="WEIRD"), "state"),
    (issue_node(state=None), "state"),
    (issue_node(labels=conn(["plan-approved"], "name", total=101, more=True)), "labels"),
    (issue_node(labels=conn(["plan-approved"], "name", total=2)), "labels"),
    (issue_node(labels=conn(["plan-approved"], "name", more=True)), "labels"),
    (issue_node(assignees=conn(["a"], "login", total=11, more=True)), "assignees"),
    (issue_node(assignees=conn([""], "login")), "assignees"),
    (issue_node(assignees={"nodes": [{"login": "a"}]}), "assignees"),
    (issue_node(assignees={"totalCount": True, "pageInfo": {}, "nodes": []}), "assignees"),
    (
        issue_node(assignees={"totalCount": 0, "pageInfo": {"hasNextPage": 0}, "nodes": []}),
        "assignees",
    ),
    (
        issue_node(assignees={"totalCount": 1, "pageInfo": {"hasNextPage": False}, "nodes": {}}),
        "assignees",
    ),
    (issue_node(assignees=None), "assignees"),
    (issue_node(labels={"totalCount": 1, "pageInfo": None, "nodes": [{"name": "x"}]}), "labels"),
    (issue_node(labels=conn(["plan-approved"], "login")), "labels"),
    (issue_node(__typename="Discussion"), "type"),
    ({"number": 1}, "type"),
    ("Issue", "not an object"),
]


@pytest.mark.parametrize(("node", "message"), BAD_NODES)
def test_parse_issue_node_rejects_bad_or_truncated_data(node: Any, message: str) -> None:
    with pytest.raises(PolicyError, match=message):
        parse_issue_node(gql(node), 1, REPO)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"data": None},
        {"data": {"repository": None}},
        {"data": {}},
        {"data": {"repository": {}}},
        {"errors": [{"message": "boom"}], "data": gql(issue_node())["data"]},
        {"errors": [], "data": gql(issue_node())["data"]},
        [],
        None,
        "",
    ],
)
def test_parse_issue_node_rejects_errors_and_empty_responses(response: Any) -> None:
    with pytest.raises(PolicyError):
        parse_issue_node(response, 1, REPO)


# --- which PR to check ----------------------------------------------------------------


@pytest.mark.parametrize("text", ["1", "42", "9999999999"])
def test_parse_pr_number_ok(text: str) -> None:
    assert parse_pr_number(text) == int(text)


@pytest.mark.parametrize(
    "text", ["", "0", "01", "-1", "+1", " 1", "1 ", "1_0", "\u0661", "1e3", "12345678901", None, 7]
)
def test_parse_pr_number_rejects(text: Any) -> None:
    with pytest.raises(PolicyError):
        parse_pr_number(text)


def queue_event(ref: str) -> dict[str, Any]:
    return {"merge_group": {"head_ref": ref, "base_ref": "refs/heads/dev"}}


def test_target_from_merge_queue_ref() -> None:
    ref = f"refs/heads/gh-readonly-queue/dev/pr-12-{SHA}"
    assert target_pr(queue_event(ref), "12") == Target(12, "dev")
    assert target_pr(queue_event(ref), None) == Target(12, "dev")
    ref = f"refs/heads/gh-readonly-queue/release/x/pr-3-{'b' * 64}"
    assert target_pr(queue_event(ref), None) == Target(3, "release/x")


@pytest.mark.parametrize(
    "ref",
    [
        f"refs/heads/gh-readonly-queue/dev/pr-12x-{SHA}",
        f"refs/heads/gh-readonly-queue/dev/pr-012-{SHA}",
        f"refs/heads/gh-readonly-queue/dev/pr-12-{SHA}-extra",
        f"refs/heads/gh-readonly-queue/dev/pr-12-{'g' * 40}",
        "refs/heads/gh-readonly-queue/dev/pr-12",
        f"refs/heads/other/dev/pr-12-{SHA}",
        f"gh-readonly-queue/dev/pr-12-{SHA}",
        f"refs/heads/gh-readonly-queue//pr-12-{SHA}",
        f"refs/heads/gh-readonly-queue/dev/pr-\u0661-{SHA}",
        "",
    ],
)
def test_target_rejects_bad_queue_ref(ref: str) -> None:
    with pytest.raises(PolicyError):
        target_pr(queue_event(ref), None)


@pytest.mark.parametrize("event", [{"merge_group": None}, {"merge_group": {"head_ref": 5}}])
def test_target_rejects_malformed_merge_group(event: dict[str, Any]) -> None:
    with pytest.raises(PolicyError):
        target_pr(event, None)


def test_target_queue_ref_must_match_pr_number() -> None:
    with pytest.raises(PolicyError, match="does not match"):
        target_pr(queue_event(f"refs/heads/gh-readonly-queue/dev/pr-12-{SHA}"), "13")


def test_target_from_pull_request_event() -> None:
    assert target_pr({"pull_request": {"number": 7}}, None) == Target(7, None)
    assert target_pr({"pull_request": {"number": 7}}, "7") == Target(7, None)
    with pytest.raises(PolicyError, match="does not match"):
        target_pr({"pull_request": {"number": 7}}, "8")


@pytest.mark.parametrize(
    "payload", [None, {}, {"number": "7"}, {"number": True}, {"number": 0}, {"number": -1}, []]
)
def test_target_rejects_bad_pull_request_payload(payload: Any) -> None:
    with pytest.raises(PolicyError):
        target_pr({"pull_request": payload}, None)


def test_target_for_dispatch_needs_pr_number() -> None:
    assert target_pr({"inputs": {"pr": "5"}}, "5") == Target(5, None)
    with pytest.raises(PolicyError, match="PR_NUMBER"):
        target_pr({}, None)
    with pytest.raises(PolicyError):
        target_pr({}, "5; rm")


@pytest.mark.parametrize("event", [None, [], "x"])
def test_target_rejects_malformed_event(event: Any) -> None:
    with pytest.raises(PolicyError):
        target_pr(event, "5")


# --- the fetched PR -------------------------------------------------------------------


def test_check_pr_ok() -> None:
    pr = api_pr()
    assert check_pr(pr, 7, REPO, None) is pr
    assert check_pr(api_pr(body=None), 7, REPO, "dev")["body"] is None
    assert check_pr(api_pr(head={"ref": "x", "repo": None}), 7, REPO, None)


BAD_PRS: list[tuple[Any, str]] = [
    (api_pr(number=8), "number"),
    (api_pr(number="7"), "number"),
    (api_pr(body=5), "body"),
    ({k: v for k, v in api_pr().items() if k != "body"}, "body"),
    (api_pr(base={"ref": "dev", "repo": {"full_name": "other/r"}}), "other/r"),
    (api_pr(base={"ref": "dev"}), "base"),
    (api_pr(base={"ref": 5, "repo": {"full_name": REPO}}), "base"),
    (api_pr(base=None), "base"),
    (api_pr(head=None), "head"),
    (api_pr(head={"ref": None, "repo": None}), "head"),
    (api_pr(head={"ref": "x", "repo": {"full_name": 5}}), "head"),
    (api_pr(head={"ref": "x", "repo": "o/r"}), "head"),
    ({}, "number"),
    ([], "not a JSON object"),
    (None, "not a JSON object"),
]


@pytest.mark.parametrize(("pr", "message"), BAD_PRS)
def test_check_pr_rejects(pr: Any, message: str) -> None:
    with pytest.raises(PolicyError, match=message):
        check_pr(pr, 7, REPO, None)


def test_check_pr_base_must_match_queue_base() -> None:
    with pytest.raises(PolicyError, match="queue"):
        check_pr(api_pr(), 7, REPO, "master")


# --- run ------------------------------------------------------------------------------


def runner(
    event: Mapping[str, Any],
    *,
    pr: Any = None,
    issues: Mapping[int, IssueInfo | None] | None = None,
    pr_number: str | None = None,
    repo: str = REPO,
) -> tuple[int, list[str], list[int]]:
    out: list[str] = []
    pulled: list[int] = []
    fresh = api_pr() if pr is None else pr
    known = {1: OK} if issues is None else issues

    def fetch_pull(n: int) -> Any:
        pulled.append(n)
        return copy.deepcopy(fresh)

    def fetch_issue(n: int) -> IssueInfo | None:
        if n not in known:
            raise PolicyError(f"GitHub API error for issue #{n}")
        return known[n]

    code = run(event, fetch_issue, fetch_pull, out.append, repo=repo, pr_number=pr_number)
    return code, out, pulled


PR_EVENT = {"pull_request": {"number": 7, "body": "Closes #1"}}


def test_run_passes() -> None:
    assert runner(PR_EVENT) == (0, ["Issue policy OK for #1."], [7])


def test_run_release_pr_is_exempt() -> None:
    code, out, _ = runner(PR_EVENT, pr=release_pr())
    assert code == 0
    assert "not applicable" in out[0]


def test_run_fork_dev_branch_is_not_a_release_pr() -> None:
    code, out, _ = runner(PR_EVENT, pr=release_pr({"full_name": "fork/r"}))
    assert code == 1
    assert "Closes #<n>" in out[0]


def test_run_uses_api_body_not_event_body() -> None:
    # The event payload says "Closes #1", but the PR as GitHub has it now does not.
    code, out, _ = runner(PR_EVENT, pr=api_pr(body="no link"))
    assert code == 1
    assert "Closes #<n>" in out[0]
    code, out, _ = runner({"pull_request": {"number": 7, "body": "x"}})
    assert code == 0


def test_run_fails_when_an_issue_fails() -> None:
    code, out, _ = runner(PR_EVENT, issues={1: None})
    assert code == 1
    assert out == ["::error::#1 is not an issue in this repository."]


def test_run_fails_when_any_of_several_issues_fails() -> None:
    bad = IssueInfo(labels=("plan-approved",), assignees=())
    code, out, _ = runner(PR_EVENT, pr=api_pr(body="Closes #1\nCloses #2"), issues={1: OK, 2: bad})
    assert code == 1
    assert out == [
        "::error::#2 is not assigned. Assign it to the person working it before work starts."
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"issues": {}}, "GitHub API error"),  # fetch error
        ({"pr": api_pr(number=9)}, "number"),  # API returned a different PR
        ({"pr": []}, "not a JSON object"),  # empty or odd response
        ({"pr_number": "x"}, "PR number"),
        ({"repo": "not a repo"}, "GITHUB_REPOSITORY"),
        ({"repo": ""}, "GITHUB_REPOSITORY"),
    ],
)
def test_run_fails_closed(kwargs: dict[str, Any], message: str) -> None:
    code, out, _ = runner(PR_EVENT, **kwargs)
    assert code == 1
    assert len(out) == 1
    assert out[0].startswith("::error::")
    assert message in out[0]


def test_run_fails_closed_on_unexpected_exceptions() -> None:
    out: list[str] = []

    def boom(n: int) -> Any:
        raise OSError("network down")

    assert run(PR_EVENT, lambda n: OK, boom, out.append, repo=REPO, pr_number=None) == 1
    assert out == ["::error::network down"]


def test_run_without_any_pr_fails() -> None:
    code, out, pulled = runner({})
    assert code == 1
    assert "PR_NUMBER" in out[0]
    assert pulled == []


def test_run_dispatch_fetches_by_number() -> None:
    assert runner({}, pr_number="7")[2] == [7]


def test_run_merge_group_fetches_queue_pr() -> None:
    event = queue_event(f"refs/heads/gh-readonly-queue/dev/pr-7-{SHA}")
    assert runner(event, pr_number="7") == (0, ["Issue policy OK for #1."], [7])
    code, out, pulled = runner(event, pr_number="8")
    assert code == 1
    assert pulled == []
    code, out, _ = runner(queue_event(f"refs/heads/gh-readonly-queue/master/pr-7-{SHA}"))
    assert code == 1
    assert "queue" in out[0]
