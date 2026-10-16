# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Enforce the AGENTS.md issue policy on pull requests.

Every PR into `dev` must close at least one issue, and each linked issue must
carry the `plan-approved` label and have an assignee. Release PRs
(head `dev` -> base `master`) are exempt.

Two extra rules (#224) stop an app with write access (the Claude Code Action
pilot) from approving its own plan or merging its own work:
- `plan-approved` counts only when its latest `labeled` event came from a
  person or from github-actions[bot] (the Copilot Autofix conformance
  workflow, #83). Another bot, or no such event, fails;
- a PR whose author GitHub does not report as a person (`user.type` is not
  `User`, or the login is missing) needs an approving review from a
  maintainer on its current head commit. Approving does not re-run this
  check: re-run it. Commit authors are not used: git metadata is
  self-asserted, so it can't prove who pushed.
Every decision uses data fetched from the GitHub API for this repository, and
every missing field or API error fails the check.

Runs in CI with GITHUB_TOKEN, GITHUB_REPOSITORY and GITHUB_EVENT_PATH set.
The PR is re-read through the API (by number, from the event or from the
PR_NUMBER variable of a workflow_dispatch run), so a body edited after the
event, for example by the Copilot Autofix conformance workflow (#83), counts.
Standard library only, so the workflow needs no install step.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b", re.IGNORECASE)
APPROVED_LABEL = "plan-approved"
MAINTAINERS = ("Reid-n0rc",)
"""Code owners (.github/CODEOWNERS) whose review approves a bot's PR."""
TRUSTED_LABEL_BOTS = ("github-actions[bot]",)
"""Bots allowed to add `plan-approved` (Copilot Autofix conformance, #83)."""
VERDICTS = ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")
"""Review states that set a reviewer's verdict (COMMENTED does not)."""
UNKNOWN_ACTOR = "an unknown account"


@dataclass(frozen=True)
class IssueInfo:
    labels: tuple[str, ...]
    assignees: tuple[str, ...]
    is_pull_request: bool = False
    untrusted_approver: str | None = None
    """Who added `plan-approved`, when that isn't a person or a trusted bot."""


@dataclass(frozen=True)
class Review:
    user: str
    state: str
    commit_id: str


def linked_issues(body: str | None) -> list[int]:
    """Issue numbers the PR body closes, deduplicated, in order of appearance."""
    seen: dict[int, None] = {}
    for match in CLOSING.finditer(body or ""):
        seen.setdefault(int(match.group(1)), None)
    return list(seen)


def is_release_pr(pr: Mapping[str, Any] | None) -> bool:
    """True for release PRs, which promote `dev` to `master` and close no issue."""
    if not pr:
        return False
    base = pr.get("base") or {}
    head = pr.get("head") or {}
    if base.get("ref") != "master" or head.get("ref") != "dev":
        return False
    if "repo" not in base and "repo" not in head:
        # `gh pr view` shape (ready_to_merge.py), which has no repo fields.
        return True
    # API shape: a fork's branch named `dev` (or a deleted fork) is not a release PR.
    base_repo = (base.get("repo") or {}).get("full_name")
    head_repo = (head.get("repo") or {}).get("full_name")
    return bool(base_repo) and head_repo == base_repo


def policy_problems(numbers: Sequence[int], issues: Mapping[int, IssueInfo | None]) -> list[str]:
    """Policy violations for a PR, given its linked issues (None = not found)."""
    if not numbers:
        return [
            "PR body must link its issue with `Closes #<n>` "
            "(AGENTS.md: no work without an approved issue)."
        ]
    problems: list[str] = []
    for n in numbers:
        issue = issues.get(n)
        if issue is None or issue.is_pull_request:
            problems.append(f"#{n} is not an issue in this repository.")
            continue
        if APPROVED_LABEL not in issue.labels:
            problems.append(f"#{n} does not have the `{APPROVED_LABEL}` label.")
        elif issue.untrusted_approver:
            problems.append(
                f"#{n}: `{APPROVED_LABEL}` was added by '{issue.untrusted_approver}'. "
                "Only the maintainer approves plans."
            )
        if not issue.assignees:
            problems.append(
                f"#{n} is not assigned. Assign it to the person working it before work starts."
            )
    return problems


def untrusted_label_actor(events: Sequence[Mapping[str, Any]]) -> str | None:
    """Who last added `plan-approved`, when that isn't trusted; None when it is.

    `events` is the issue's event list, oldest first. Only the most recent
    `labeled` event for the label counts. A person (`User`) or a trusted bot
    is trusted. Anything else fails closed: another bot, a missing actor, or
    no `labeled` event at all (returned as UNKNOWN_ACTOR).
    """
    found = False
    actor: Mapping[str, Any] = {}
    for event in events:
        label = event.get("label") or {}
        name = str(label.get("name") or "").lower()
        if event.get("event") == "labeled" and name == APPROVED_LABEL:
            found = True
            actor = event.get("actor") or {}
    login = str(actor.get("login") or "")
    if not found or not login:
        return UNKNOWN_ACTOR
    if actor.get("type") == "User" or (actor.get("type") == "Bot" and login in TRUSTED_LABEL_BOTS):
        return None
    return login


def automation_reason(pr: Mapping[str, Any]) -> str | None:
    """Why the PR counts as automated (and needs a maintainer's approval), or None.

    A PR is automated when GitHub does not report a person (`User`) as its
    author. A missing author or login fails closed.
    """
    user = pr.get("user") or {}
    login = str(user.get("login") or "")
    if user.get("type") != "User" or not login:
        return f"PR by '{login or UNKNOWN_ACTOR}'"
    return None


def parse_reviews(data: Sequence[Mapping[str, Any]]) -> list[Review]:
    return [
        Review(
            str((r.get("user") or {}).get("login", "")),
            str(r.get("state", "")),
            str(r.get("commit_id", "")),
        )
        for r in data
    ]


def bot_pr_problems(
    pr: Mapping[str, Any],
    reviews: Sequence[Review],
) -> list[str]:
    """For an automated PR, require a maintainer's approval of the current head commit.

    `reviews` are oldest first. A maintainer's latest approving, rejecting, or
    dismissed review is their verdict. Plain comments do not change it.
    """
    reason = automation_reason(pr)
    if reason is None:
        return []
    head = str((pr.get("head") or {}).get("sha") or "")
    verdict: dict[str, Review] = {}
    for review in reviews:
        if review.user in MAINTAINERS and review.state in VERDICTS:
            verdict[review.user] = review
    if head and any(r.state == "APPROVED" and r.commit_id == head for r in verdict.values()):
        return []
    owners = ", ".join(f"@{m}" for m in MAINTAINERS)
    return [
        f"{reason} needs an approving review from {owners} on its current head "
        f"({head[:7]}). Approve it, then re-run this check."
    ]


def issue_in_repo(data: Mapping[str, Any], repo: str) -> bool:
    """True when the API's issue belongs to `repo` (a transferred issue redirects elsewhere)."""
    return data.get("repository_url") == f"https://api.github.com/repos/{repo}"


def parse_issue(data: Mapping[str, Any]) -> IssueInfo:
    labels = tuple(
        label if isinstance(label, str) else str(label.get("name", ""))
        for label in data.get("labels") or []
    )
    assignees = tuple(str(a.get("login", "")) for a in data.get("assignees") or [])
    return IssueInfo(labels, assignees, bool(data.get("pull_request")))


def fetch_issue(repo: str, number: int, token: str) -> IssueInfo | None:  # pragma: no cover
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{number}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise RuntimeError(f"GitHub API returned {err.code} for issue #{number}") from err
    if not issue_in_repo(data, repo):
        return None
    return parse_issue(data)


def _get_all(url: str, token: str) -> list[dict[str, Any]]:  # pragma: no cover
    """Every item of a paginated list endpoint, oldest first."""
    items: list[dict[str, Any]] = []
    for page in range(1, 51):
        req = urllib.request.Request(
            f"{url}?per_page=100&page={page}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch = json.load(resp)
        if not isinstance(batch, list):
            raise RuntimeError(f"GitHub API returned no list for {url}")
        items.extend(batch)
        if len(batch) < 100:
            return items
    raise RuntimeError(f"Too many items at {url} to check")


def fetch_checked_issue(repo: str, number: int, token: str) -> IssueInfo | None:  # pragma: no cover
    """The issue, plus who added its `plan-approved` label when that isn't trusted."""
    info = fetch_issue(repo, number, token)
    if info is None or APPROVED_LABEL not in info.labels:
        return info
    events = _get_all(f"https://api.github.com/repos/{repo}/issues/{number}/events", token)
    return replace(info, untrusted_approver=untrusted_label_actor(events))


def fetch_pr_reviews(repo: str, number: int, token: str) -> list[Review]:  # pragma: no cover
    url = f"https://api.github.com/repos/{repo}/pulls/{number}/reviews"
    return parse_reviews(_get_all(url, token))


def fetch_pr(repo: str, number: int, token: str) -> dict[str, Any]:  # pragma: no cover
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls/{number}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data: dict[str, Any] = json.load(resp)
        return data


def current_pr(
    event: Mapping[str, Any],
    pr_number: int | None,
    fetch: Callable[[int], Mapping[str, Any]] | None,
) -> Mapping[str, Any] | None:
    """The PR as it is now: fetched by number when possible, else the event payload."""
    payload = event.get("pull_request")
    number = pr_number or (payload or {}).get("number")
    if fetch is not None and number:
        return fetch(int(number))
    return payload


def run(
    event: Mapping[str, Any],
    fetch: Callable[[int], IssueInfo | None],
    out: Callable[[str], None] = print,
    *,
    fetch_pull: Callable[[int], Mapping[str, Any]] | None = None,
    pr_number: int | None = None,
    fetch_reviews: Callable[[int], Sequence[Review]] | None = None,
) -> int:
    pr = current_pr(event, pr_number, fetch_pull)
    if pr is None:
        out("::error::No pull request to check (pass PR_NUMBER for workflow_dispatch runs).")
        return 1
    if is_release_pr(pr):
        out("Release PR (dev -> master): issue policy not applicable.")
        return 0
    numbers = linked_issues((pr or {}).get("body"))
    issues = {n: fetch(n) for n in numbers}
    problems = policy_problems(numbers, issues)
    number = pr.get("number")
    if automation_reason(pr):
        # No reviews to read (no number or no fetcher) fails closed.
        reviews = fetch_reviews(int(number)) if fetch_reviews and number else []
        problems += bot_pr_problems(pr, reviews)
    if problems:
        for p in problems:
            out(f"::error::{p}")
        return 1
    out("Issue policy OK for " + ", ".join(f"#{n}" for n in numbers) + ".")
    return 0


def main() -> int:  # pragma: no cover
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
        event = json.load(fh)
    pr_number = int(os.environ["PR_NUMBER"]) if os.environ.get("PR_NUMBER") else None
    try:
        return run(
            event,
            lambda n: fetch_checked_issue(repo, n, token),
            fetch_pull=lambda n: fetch_pr(repo, n, token),
            pr_number=pr_number,
            fetch_reviews=lambda n: fetch_pr_reviews(repo, n, token),
        )
    except Exception as exc:
        print(f"::error::{exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
