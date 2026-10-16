# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Enforce the AGENTS.md issue policy on pull requests.

Every PR into `dev` must close at least one issue, and each linked issue must
carry the `plan-approved` label and have an assignee. Release PRs
(head `dev` -> base `master`) are exempt.

Bots get two extra rules (#224), so an app with write access (the Claude Code
Action pilot) can neither approve its own plan nor merge its own PR:
- a `plan-approved` label added by a bot does not count, except one added by
  github-actions[bot] (the Copilot Autofix conformance workflow, #83);
- a PR opened by a bot needs an approving review from a maintainer on its
  current head commit. Approving does not re-run this check: re-run it.

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


@dataclass(frozen=True)
class IssueInfo:
    labels: tuple[str, ...]
    assignees: tuple[str, ...]
    is_pull_request: bool = False
    approved_by_bot: str | None = None
    """The untrusted bot that added `plan-approved`, if one did."""


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
    return bool(
        pr.get("base", {}).get("ref") == "master" and pr.get("head", {}).get("ref") == "dev"
    )


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
        elif issue.approved_by_bot:
            problems.append(
                f"#{n}: `{APPROVED_LABEL}` was added by '{issue.approved_by_bot}'. "
                "Only the maintainer approves plans."
            )
        if not issue.assignees:
            problems.append(
                f"#{n} is not assigned. Assign it to the person working it before work starts."
            )
    return problems


def bot_label_actor(events: Sequence[Mapping[str, Any]]) -> str | None:
    """The untrusted bot that last added `plan-approved`, or None.

    `events` is the issue's event list, oldest first. Only the most recent
    `labeled` event for the label counts.
    """
    actor: Mapping[str, Any] | None = None
    for event in events:
        label = event.get("label") or {}
        if event.get("event") == "labeled" and label.get("name") == APPROVED_LABEL:
            actor = event.get("actor") or {}
    if actor is None or actor.get("type") != "Bot":
        return None
    login = str(actor.get("login", ""))
    return None if login in TRUSTED_LABEL_BOTS else login


def is_bot_pr(pr: Mapping[str, Any]) -> bool:
    """True when a GitHub App or bot account opened the PR."""
    return bool((pr.get("user") or {}).get("type") == "Bot")


def parse_reviews(data: Sequence[Mapping[str, Any]]) -> list[Review]:
    return [
        Review(
            str((r.get("user") or {}).get("login", "")),
            str(r.get("state", "")),
            str(r.get("commit_id", "")),
        )
        for r in data
    ]


def bot_pr_problems(pr: Mapping[str, Any], reviews: Sequence[Review]) -> list[str]:
    """For a bot's PR, require a maintainer's approval of the current head commit.

    `reviews` are oldest first. A maintainer's latest approving, rejecting, or
    dismissed review is their verdict. Plain comments do not change it.
    """
    if not is_bot_pr(pr):
        return []
    head = str((pr.get("head") or {}).get("sha", ""))
    verdict: dict[str, Review] = {}
    for review in reviews:
        if review.user in MAINTAINERS and review.state in VERDICTS:
            verdict[review.user] = review
    if head and any(r.state == "APPROVED" and r.commit_id == head for r in verdict.values()):
        return []
    login = (pr.get("user") or {}).get("login", "a bot")
    owners = ", ".join(f"@{m}" for m in MAINTAINERS)
    return [
        f"PR by '{login}' needs an approving review from {owners} on its current head "
        f"({head[:7]}). Approve it, then re-run this check."
    ]


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
            return parse_issue(json.load(resp))
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise RuntimeError(f"GitHub API returned {err.code} for issue #{number}") from err


def _get_all(url: str, token: str) -> list[dict[str, Any]]:  # pragma: no cover
    """Every item of a paginated list endpoint, oldest first."""
    items: list[dict[str, Any]] = []
    for page in range(1, 51):
        req = urllib.request.Request(
            f"{url}?per_page=100&page={page}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            batch: list[dict[str, Any]] = json.load(resp)
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


def fetch_checked_issue(repo: str, number: int, token: str) -> IssueInfo | None:  # pragma: no cover
    """The issue, plus which bot (if any) added its `plan-approved` label."""
    info = fetch_issue(repo, number, token)
    if info is None or APPROVED_LABEL not in info.labels:
        return info
    events = _get_all(f"https://api.github.com/repos/{repo}/issues/{number}/events", token)
    return replace(info, approved_by_bot=bot_label_actor(events))


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
    if is_bot_pr(pr):
        number = pr.get("number")
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
