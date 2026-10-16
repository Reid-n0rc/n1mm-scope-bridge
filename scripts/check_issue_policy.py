# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Enforce the AGENTS.md issue policy on pull requests.

Every PR into `dev` must close at least one issue, and each linked issue must
be an open issue in this repository with the `plan-approved` label and an
assignee. Release PRs (head `dev` of this repository -> base `master`) are
exempt.

Runs in CI with GITHUB_TOKEN, GITHUB_REPOSITORY and GITHUB_EVENT_PATH set.
The PR is always re-read through the API by number, so a body edited after the
event, for example by the Copilot Autofix conformance workflow (#83), counts.
The number comes from the `pull_request` event, from the merge queue ref of a
`merge_group` event, or from the PR_NUMBER variable of a workflow_dispatch run.

The check fails closed (#247): any API error, empty response, missing or
malformed field, or possibly truncated list fails it. Linked issues are read
from GitHub's GraphQL API for this repository only, and labels and assignees
are only trusted when GitHub reports the complete list. Standard library only,
so the workflow needs no install step.

GitHub fills `closingIssuesReferences` only for PRs into the default branch
(`master`), so the PR body's `Closes #<n>` keywords stay the source of the
issue numbers for PRs into `dev`. Each number is then checked against GitHub's
own data.
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

CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#([0-9]{1,10})\b", re.IGNORECASE | re.ASCII
)
APPROVED_LABEL = "plan-approved"
PR_NUMBER = re.compile(r"[1-9][0-9]{0,9}")
REPO_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")
QUEUE_REF = re.compile(
    r"refs/heads/gh-readonly-queue/(?P<base>[A-Za-z0-9._/-]+)"
    r"/pr-(?P<number>[1-9][0-9]{0,9})-(?:[0-9a-f]{40}|[0-9a-f]{64})"
)
PAGE = 100  # labels and assignees requested per issue; more than this fails the check
ISSUE_QUERY = f"""
query($owner: String!, $name: String!, $number: Int!) {{
  repository(owner: $owner, name: $name) {{
    issueOrPullRequest(number: $number) {{
      __typename
      ... on Issue {{
        number
        state
        repository {{ nameWithOwner }}
        labels(first: {PAGE}) {{ totalCount pageInfo {{ hasNextPage }} nodes {{ name }} }}
        assignees(first: {PAGE}) {{ totalCount pageInfo {{ hasNextPage }} nodes {{ login }} }}
      }}
    }}
  }}
}}
"""


class PolicyError(RuntimeError):
    """Data the check cannot trust. The check fails rather than guessing."""


@dataclass(frozen=True)
class IssueInfo:
    labels: tuple[str, ...]
    assignees: tuple[str, ...]
    is_pull_request: bool = False
    is_open: bool = True


@dataclass(frozen=True)
class Target:
    """The PR to check, and the base branch of its merge queue (merge_group runs)."""

    number: int
    queue_base: str | None


def linked_issues(body: str | None) -> list[int]:
    """Issue numbers the PR body closes, deduplicated, in order of appearance."""
    seen: dict[int, None] = {}
    for match in CLOSING.finditer(body or ""):
        seen.setdefault(int(match.group(1)), None)
    return list(seen)


def _repo_name(side: Any) -> str | None:
    repo = side.get("repo") if isinstance(side, Mapping) else None
    name = repo.get("full_name") if isinstance(repo, Mapping) else None
    return name if isinstance(name, str) else None


def is_release_pr(pr: Mapping[str, Any] | None, repo: str | None = None) -> bool:
    """True for release PRs, which promote `dev` to `master` and close no issue.

    With ``repo``, both the head and the base must be that repository, so a
    fork's branch named `dev` is not a release PR.
    """
    if not pr:
        return False
    base, head = pr.get("base") or {}, pr.get("head") or {}
    if not (base.get("ref") == "master" and head.get("ref") == "dev"):
        return False
    return repo is None or _repo_name(base) == _repo_name(head) == repo


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
        if not issue.is_open:
            problems.append(f"#{n} is closed. Link an open issue.")
        if APPROVED_LABEL not in issue.labels:
            problems.append(f"#{n} does not have the `{APPROVED_LABEL}` label.")
        if not issue.assignees:
            problems.append(
                f"#{n} is not assigned. Assign it to the person working it before work starts."
            )
    return problems


def _name(item: Any, key: str, what: str) -> str:
    value = item.get(key) if isinstance(item, Mapping) else None
    if not isinstance(value, str) or not value:
        raise PolicyError(f"{what}: an entry has no `{key}` in the API response.")
    return value


def parse_issue(data: Any) -> IssueInfo:
    """An issue from the REST API (`gh api repos/<repo>/issues/<n>`)."""
    if not isinstance(data, Mapping):
        raise PolicyError("Issue response is not a JSON object.")
    labels, assignees = data.get("labels") or [], data.get("assignees") or []
    if not isinstance(labels, list) or not isinstance(assignees, list):
        raise PolicyError("Issue labels or assignees are not lists in the API response.")
    state = data.get("state", "open")
    if state not in ("open", "closed"):
        raise PolicyError(f"Issue has an unexpected state {state!r}.")
    return IssueInfo(
        tuple(
            label if isinstance(label, str) else _name(label, "name", "labels") for label in labels
        ),
        tuple(_name(a, "login", "assignees") for a in assignees),
        bool(data.get("pull_request")),
        state == "open",
    )


def _complete(node: Mapping[str, Any], field: str, key: str, number: int) -> tuple[str, ...]:
    """Every value of a GraphQL connection, or PolicyError if it may be truncated."""
    what = f"#{number} {field}"
    conn = node.get(field)
    if not isinstance(conn, Mapping):
        raise PolicyError(f"{what} are missing from the API response.")
    total, page, nodes = conn.get("totalCount"), conn.get("pageInfo"), conn.get("nodes")
    more = page.get("hasNextPage") if isinstance(page, Mapping) else None
    if type(total) is not int or more is not False or not isinstance(nodes, list):
        raise PolicyError(f"{what}: the API response is incomplete.")
    if len(nodes) != total:
        raise PolicyError(f"{what}: GitHub lists {total} but returned {len(nodes)}.")
    return tuple(_name(item, key, what) for item in nodes)


def parse_issue_node(response: Any, number: int, repo: str) -> IssueInfo | None:
    """An issue from the GraphQL ISSUE_QUERY response (None = no such number)."""
    if not isinstance(response, Mapping) or "errors" in response:
        errors = response.get("errors") if isinstance(response, Mapping) else None
        raise PolicyError(f"GitHub GraphQL error for #{number}: {errors or 'no data'}")
    data = response.get("data")
    found = data.get("repository") if isinstance(data, Mapping) else None
    if not isinstance(found, Mapping) or "issueOrPullRequest" not in found:
        raise PolicyError(f"GitHub GraphQL returned no repository data for #{number}.")
    node = found["issueOrPullRequest"]
    if node is None:
        return None
    if not isinstance(node, Mapping):
        raise PolicyError(f"API response for #{number} is not an object.")
    kind = node.get("__typename")
    if kind == "PullRequest":
        return IssueInfo((), (), is_pull_request=True, is_open=False)
    if kind != "Issue":
        raise PolicyError(f"#{number} has an unexpected type {kind!r}.")
    if node.get("number") != number:
        raise PolicyError(f"GitHub returned issue number {node.get('number')!r} for #{number}.")
    owner = node.get("repository")
    if not isinstance(owner, Mapping):
        raise PolicyError(f"#{number} has no repository in the API response.")
    if owner.get("nameWithOwner") != repo:
        raise PolicyError(f"#{number} belongs to {owner.get('nameWithOwner')!r}, not {repo}.")
    state = node.get("state")
    if state not in ("OPEN", "CLOSED"):
        raise PolicyError(f"#{number} has an unexpected state {state!r}.")
    return IssueInfo(
        _complete(node, "labels", "name", number),
        _complete(node, "assignees", "login", number),
        is_pull_request=False,
        is_open=state == "OPEN",
    )


def parse_pr_number(text: Any) -> int:
    """A PR number from text: ASCII digits only, no sign, spaces or leading zero."""
    if not isinstance(text, str) or not PR_NUMBER.fullmatch(text):
        raise PolicyError(f"Invalid PR number {text!r}.")
    return int(text)


def target_pr(event: Any, pr_number: str | None) -> Target:
    """The PR this run checks, from GitHub's event data (and PR_NUMBER, which must agree)."""
    if not isinstance(event, Mapping):
        raise PolicyError("The event payload is not a JSON object.")
    given = None if pr_number is None else parse_pr_number(pr_number)
    if "merge_group" in event:
        group = event["merge_group"]
        ref = group.get("head_ref") if isinstance(group, Mapping) else None
        match = QUEUE_REF.fullmatch(ref) if isinstance(ref, str) else None
        if match is None:
            raise PolicyError(f"Unexpected merge queue ref {ref!r}.")
        target = Target(int(match.group("number")), match.group("base"))
    elif "pull_request" in event:
        payload = event["pull_request"]
        number = payload.get("number") if isinstance(payload, Mapping) else None
        if type(number) is not int or number < 1:
            raise PolicyError(f"The pull_request event has no valid PR number ({number!r}).")
        target = Target(number, None)
    elif given is None:
        raise PolicyError("No pull request to check (pass PR_NUMBER for workflow_dispatch runs).")
    else:
        return Target(given, None)
    if given is not None and given != target.number:
        raise PolicyError(f"PR_NUMBER {given} does not match the event's PR #{target.number}.")
    return target


def check_pr(pr: Any, number: int, repo: str, queue_base: str | None) -> Mapping[str, Any]:
    """The fetched PR, after checking it is PR ``number`` of ``repo`` and well formed."""
    if not isinstance(pr, Mapping):
        raise PolicyError(f"PR #{number} response is not a JSON object.")
    if type(pr.get("number")) is not int or pr.get("number") != number:
        raise PolicyError(f"GitHub returned PR number {pr.get('number')!r} for #{number}.")
    if "body" not in pr or not isinstance(pr["body"], (str, type(None))):
        raise PolicyError(f"PR #{number} body is missing or not text.")
    base, head = pr.get("base"), pr.get("head")
    if not isinstance(base, Mapping) or not isinstance(base.get("ref"), str):
        raise PolicyError(f"PR #{number} base is missing or malformed.")
    if _repo_name(base) is None:
        raise PolicyError(f"PR #{number} base repository is missing.")
    if _repo_name(base) != repo:
        raise PolicyError(f"PR #{number} targets {_repo_name(base)}, not {repo}.")
    head_repo = head.get("repo") if isinstance(head, Mapping) else None
    if (
        not isinstance(head, Mapping)
        or not isinstance(head.get("ref"), str)
        or (head_repo is not None and _repo_name(head) is None)
    ):
        raise PolicyError(f"PR #{number} head is missing or malformed.")
    if queue_base is not None and base["ref"] != queue_base:
        raise PolicyError(
            f"PR #{number} targets {base['ref']}, but the merge queue is for {queue_base}."
        )
    return pr


def run(
    event: Any,
    fetch: Callable[[int], IssueInfo | None],
    fetch_pull: Callable[[int], Any],
    out: Callable[[str], None] = print,
    *,
    repo: str,
    pr_number: str | None,
) -> int:
    """Check the PR. Returns 0 only when every check passed on complete data."""
    try:
        if not isinstance(repo, str) or not REPO_NAME.fullmatch(repo):
            raise PolicyError(f"Invalid GITHUB_REPOSITORY {repo!r}.")
        target = target_pr(event, pr_number)
        pr = check_pr(fetch_pull(target.number), target.number, repo, target.queue_base)
        if is_release_pr(pr, repo):
            out("Release PR (dev -> master): issue policy not applicable.")
            return 0
        numbers = linked_issues(pr["body"])
        problems = policy_problems(numbers, {n: fetch(n) for n in numbers})
    except Exception as exc:  # fail closed on anything unexpected
        out(f"::error::{exc}")
        return 1
    if problems:
        for p in problems:
            out(f"::error::{p}")
        return 1
    out("Issue policy OK for " + ", ".join(f"#{n}" for n in numbers) + ".")
    return 0


def _api(url: str, token: str, payload: Any = None) -> Any:  # pragma: no cover - network
    req = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        method="GET" if payload is None else "POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as err:
        raise PolicyError(f"GitHub API returned HTTP {err.code} for {url}") from err
    except OSError as err:
        raise PolicyError(f"GitHub API request to {url} failed: {err}") from err
    if status != 200 or not raw:
        raise PolicyError(f"GitHub API returned HTTP {status} with no usable data for {url}")
    try:
        return json.loads(raw)
    except ValueError as err:
        raise PolicyError(f"GitHub API returned invalid JSON for {url}") from err


def fetch_issue(repo: str, number: int, token: str) -> IssueInfo | None:  # pragma: no cover
    owner, name = repo.split("/", 1)
    variables = {"owner": owner, "name": name, "number": number}
    query = {"query": ISSUE_QUERY, "variables": variables}
    return parse_issue_node(_api("https://api.github.com/graphql", token, query), number, repo)


def fetch_pr(repo: str, number: int, token: str) -> Any:  # pragma: no cover - network
    return _api(f"https://api.github.com/repos/{repo}/pulls/{number}", token)


def main() -> int:  # pragma: no cover
    try:
        token = os.environ["GITHUB_TOKEN"]
        repo = os.environ["GITHUB_REPOSITORY"]
        if not token:
            raise PolicyError("GITHUB_TOKEN is empty.")
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
            event = json.load(fh)
    except Exception as exc:
        print(f"::error::Cannot read the workflow environment: {exc!r}")
        return 1
    return run(
        event,
        lambda n: fetch_issue(repo, n, token),
        lambda n: fetch_pr(repo, n, token),
        repo=repo,
        pr_number=os.environ.get("PR_NUMBER") or None,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
