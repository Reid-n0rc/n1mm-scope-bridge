# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Enforce the AGENTS.md issue policy on pull requests.

Every PR into `dev` must close at least one issue, and each linked issue must
carry the `plan-approved` label and have an assignee. Release PRs
(head `dev` -> base `master`) are exempt.

Runs in CI with GITHUB_TOKEN, GITHUB_REPOSITORY and GITHUB_EVENT_PATH set.
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
from dataclasses import dataclass
from typing import Any

CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b", re.IGNORECASE)
APPROVED_LABEL = "plan-approved"


@dataclass(frozen=True)
class IssueInfo:
    labels: tuple[str, ...]
    assignees: tuple[str, ...]
    is_pull_request: bool = False


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
        if not issue.assignees:
            problems.append(
                f"#{n} is not assigned. Assign it to the person working it before work starts."
            )
    return problems


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


def run(
    event: Mapping[str, Any],
    fetch: Callable[[int], IssueInfo | None],
    out: Callable[[str], None] = print,
) -> int:
    pr = event.get("pull_request")
    if is_release_pr(pr):
        out("Release PR (dev -> master): issue policy not applicable.")
        return 0
    numbers = linked_issues((pr or {}).get("body"))
    issues = {n: fetch(n) for n in numbers}
    problems = policy_problems(numbers, issues)
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
    try:
        return run(event, lambda n: fetch_issue(repo, n, token))
    except Exception as exc:
        print(f"::error::{exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
