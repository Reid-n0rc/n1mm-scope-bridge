# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Detect and report automated PRs and code-scanning alerts that need adopting (#78).

Read-mostly by design. It labels automated PRs (Copilot Autofix
``alert-autofix-*`` and Dependabot ``dependabot/*``) ``needs-adoption``,
posts one explanatory comment on each, and keeps a single "Automated PR
triage" issue listing everything pending. It never creates plan-approved
issues, never commits to PR branches, never re-runs checks, and never merges:
adoption follows AGENTS.md "Automated PRs" and is done by a person or agent.

Runs in GitHub Actions with GITHUB_TOKEN and GITHUB_REPOSITORY set:

    python scripts/automation_triage.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

AUTOMATED_PREFIXES = ("alert-autofix-", "dependabot/")
LABEL = "needs-adoption"
LABEL_COLOR = "D93F0B"
LABEL_DESCRIPTION = "Automated PR or alert waiting to be adopted (AGENTS.md: Automated PRs)"
TRIAGE_TITLE = "Automated PR triage"
TRIAGE_LABEL = "process"
MARKER = "<!-- automation-triage -->"
COMMENT = f"""{MARKER}
This automated PR needs **adoption** before it can merge (AGENTS.md, *Automated PRs*).
Bots get no exemption from the **Issue policy** and **Changelog** checks.

- **Adopt it:** link a `plan-approved`, assigned issue (`Closes #<n>` in the PR body) and
  push a `changelog.d/<issue>.<type>.md` fragment plus any fixes to this branch through the
  normal process. CI then runs on the pushed commit.
- **Or replace it:** close this PR with a link to a tracked PR that does the work properly.

This comment and the `{LABEL}` label are added by `scripts/automation_triage.py`, which only
reports. It never adopts, edits, re-runs checks on, or merges a PR.
"""


class Api(Protocol):
    def request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        """Call the GitHub REST API; return the decoded JSON (None for 204)."""


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API {status}: {message}")
        self.status = status


class RestApi:  # pragma: no cover - real network
    def __init__(self, repo: str, token: str) -> None:
        self.base = f"https://api.github.com/repos/{repo}"
        self.token = token

    def request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            raise ApiError(err.code, err.read().decode(errors="replace")[:200]) from None
        return json.loads(raw) if raw else None


@dataclass(frozen=True)
class Pending:
    kind: str  # "pr" or "alert"
    number: int
    title: str
    url: str


def is_automated(pr: Mapping[str, Any]) -> bool:
    return str(pr.get("head", {}).get("ref", "")).startswith(AUTOMATED_PREFIXES)


CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+\b", re.IGNORECASE)


def is_adopted(pr: Mapping[str, Any]) -> bool:
    """True once the PR links its tracking issue (by a person, an agent, or #83's workflow)."""
    return bool(CLOSING.search(str(pr.get("body") or "")))


def has_label(pr: Mapping[str, Any]) -> bool:
    return any(
        (lb.get("name") if isinstance(lb, Mapping) else lb) == LABEL
        for lb in pr.get("labels") or []
    )


def referenced_alerts(prs: Sequence[Mapping[str, Any]]) -> set[int]:
    """Alert numbers mentioned by any open PR (title or body)."""
    found: set[int] = set()
    pattern = re.compile(r"code-scanning/(\d+)|alert no\.?\s*(\d+)", re.IGNORECASE)
    for pr in prs:
        text = f"{pr.get('title', '')}\n{pr.get('body') or ''}"
        for a, b in pattern.findall(text):
            found.add(int(a or b))
    return found


def open_alerts(api: Api, warn: Callable[[str], object]) -> list[Mapping[str, Any]]:
    try:
        return list(api.request("GET", "/code-scanning/alerts?state=open&per_page=100") or [])
    except ApiError as err:
        # Code scanning disabled or no access: report nothing rather than fail the run.
        warn(f"could not list code-scanning alerts ({err})")
        return []


def find_pending(api: Api, warn: Callable[[str], object] = print) -> list[Pending]:
    prs = list(api.request("GET", "/pulls?state=open&per_page=100") or [])
    pending = [
        Pending("pr", pr["number"], pr["title"], pr["html_url"])
        for pr in prs
        if is_automated(pr) and not is_adopted(pr)
    ]
    covered = referenced_alerts(prs)
    for alert in open_alerts(api, warn):
        if alert["number"] not in covered:
            rule = alert.get("rule", {})
            title = rule.get("description") or rule.get("id") or "code-scanning alert"
            pending.append(Pending("alert", alert["number"], title, alert["html_url"]))
    return pending


def ensure_label(api: Api) -> None:
    try:
        api.request("GET", f"/labels/{LABEL}")
    except ApiError as err:
        if err.status != 404:
            raise
        api.request(
            "POST",
            "/labels",
            {"name": LABEL, "color": LABEL_COLOR, "description": LABEL_DESCRIPTION},
        )


def flag_pr(api: Api, number: int) -> None:
    """Label the PR and post the explanatory comment once."""
    api.request("POST", f"/issues/{number}/labels", {"labels": [LABEL]})
    comments = api.request("GET", f"/issues/{number}/comments?per_page=100") or []
    if not any(MARKER in (c.get("body") or "") for c in comments):
        api.request("POST", f"/issues/{number}/comments", {"body": COMMENT})


def render_body(pending: Sequence[Pending]) -> str:
    lines = [
        MARKER,
        "Maintained by `scripts/automation_triage.py` (workflow *Automation triage*). It only",
        "reports: adoption follows AGENTS.md, *Automated PRs*.",
        "",
    ]
    if not pending:
        lines.append("Nothing is waiting for adoption.")
    else:
        lines.append("Waiting for adoption:")
        lines.append("")
        for p in pending:
            kind = "PR" if p.kind == "pr" else "Code-scanning alert"
            lines.append(f"- [ ] {kind} #{p.number}: [{p.title}]({p.url})")
    return "\n".join(lines) + "\n"


def find_triage_issue(api: Api) -> Mapping[str, Any] | None:
    issues = api.request("GET", f"/issues?state=all&labels={TRIAGE_LABEL}&per_page=100") or []
    for issue in issues:
        if issue.get("title") == TRIAGE_TITLE and "pull_request" not in issue:
            found: Mapping[str, Any] = issue
            return found
    return None


def update_triage_issue(api: Api, pending: Sequence[Pending]) -> str:
    """Create, update, close, or reopen the triage issue. Returns what was done."""
    issue = find_triage_issue(api)
    body = render_body(pending)
    if issue is None:
        if not pending:
            return "no triage issue needed"
        created = api.request(
            "POST", "/issues", {"title": TRIAGE_TITLE, "body": body, "labels": [TRIAGE_LABEL]}
        )
        return f"created triage issue #{created['number']}"
    state = "open" if pending else "closed"
    changes: dict[str, Any] = {}
    if issue.get("body") != body:
        changes["body"] = body
    if issue.get("state") != state:
        changes["state"] = state
    if not changes:
        return f"triage issue #{issue['number']} unchanged ({state})"
    api.request("PATCH", f"/issues/{issue['number']}", changes)
    return f"updated triage issue #{issue['number']} ({state})"


def unflag_adopted(api: Api) -> list[int]:
    """Remove `needs-adoption` from automated PRs that have since been adopted."""
    done = []
    for pr in api.request("GET", "/pulls?state=open&per_page=100") or []:
        if is_automated(pr) and is_adopted(pr) and has_label(pr):
            api.request("DELETE", f"/issues/{pr['number']}/labels/{LABEL}")
            done.append(int(pr["number"]))
    return done


def run(api: Api, *, dry_run: bool = False, out: Callable[[str], object] = print) -> int:
    pending = find_pending(api, warn=lambda m: out(f"::warning::{m}"))
    out(f"{len(pending)} item(s) waiting for adoption")
    for p in pending:
        out(f"  {p.kind} #{p.number}: {p.title}")
    if dry_run:
        out(render_body(pending))
        return 0
    for number in unflag_adopted(api):
        out(f"  PR #{number} adopted; removed {LABEL}")
    prs = [p for p in pending if p.kind == "pr"]
    if prs:
        ensure_label(api)
        for p in prs:
            flag_pr(api, p.number)
    out(update_triage_issue(api, pending))
    return 0


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - entry point
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="report only; change nothing")
    args = parser.parse_args(argv)
    api = RestApi(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    try:
        return run(api, dry_run=args.dry_run)
    except ApiError as err:
        print(f"::error::{err}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
