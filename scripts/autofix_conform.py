# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Bring a Copilot Autofix PR into line with the repo's procedures (issue #83).

Maintainer-approved exception to "bots never satisfy checks on their own"
(AGENTS.md, Automated PRs), for Copilot Autofix only. For a same-repo PR whose
head starts with ``alert-autofix-``, it:

1. creates or reuses the tracking issue "Code scanning alert #N: <rule>"
   (plan-approved, process, lane:core; assigned to the maintainer);
2. retargets the PR to ``dev`` and adds ``Closes #<issue>`` to its body;
3. commits ``changelog.d/<issue>.security.md`` through the contents API;
4. removes ``needs-adoption`` and re-runs the PR checks (pushes and edits made
   with the workflow token don't trigger workflows, so they are dispatched);
5. posts one summary comment.

It never merges, approves, or runs code from the PR. Standard library plus the
``gh`` CLI.

    python scripts/autofix_conform.py <pr-number>
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

HEAD_PREFIX = "alert-autofix-"
BASE = "dev"
MAINTAINER = "Reid-n0rc"
ISSUE_LABELS = ("plan-approved", "process", "lane:core")
ADOPTION_LABEL = "needs-adoption"
MARKER = "<!-- autofix-conform -->"
ALERT_URL = re.compile(r"/code-scanning/(\d+)\b")
CLOSES = re.compile(r"\bcloses\s+#(\d+)\b", re.IGNORECASE)
# (workflow file, inputs) dispatched on the PR branch after the fixes.
DISPATCH = (
    ("ci.yml", ()),
    ("codeql.yml", ()),
    ("changelog.yml", ("pr",)),
    ("issue-policy.yml", ("pr",)),
)

Gh = Callable[[Sequence[str]], tuple[int, str]]


class ConformError(Exception):
    """The PR can't be conformed automatically (reported, nothing changed)."""


def run_gh(args: Sequence[str]) -> tuple[int, str]:  # pragma: no cover - real gh
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr


@dataclass
class Result:
    pr: int
    issue: int = 0
    actions: list[str] = field(default_factory=list)


class Conformer:
    def __init__(self, repo: str, gh: Gh = run_gh) -> None:
        self.repo = repo
        self.gh = gh

    def _json(self, args: Sequence[str]) -> Any:
        code, out = self.gh(args)
        if code != 0:
            raise ConformError(f"gh {' '.join(args[:3])} failed: {out.strip()[:200]}")
        return json.loads(out)

    def _ok(self, args: Sequence[str]) -> str:
        code, out = self.gh(args)
        if code != 0:
            raise ConformError(f"gh {' '.join(args[:3])} failed: {out.strip()[:200]}")
        return out

    # -- steps -------------------------------------------------------------------

    def load_pr(self, number: int) -> dict[str, Any]:
        pr: dict[str, Any] = self._json(
            [
                "pr", "view", str(number), "--repo", self.repo, "--json",
                "number,title,body,headRefName,baseRefName,isCrossRepository,labels,state",
            ]
        )  # fmt: skip
        if pr.get("state") != "OPEN":
            raise ConformError(f"PR #{number} is not open")
        if not str(pr.get("headRefName", "")).startswith(HEAD_PREFIX):
            raise ConformError(f"PR #{number} is not a Copilot Autofix PR")
        if pr.get("isCrossRepository"):
            raise ConformError(f"PR #{number} comes from a fork; not conformed")
        return pr

    def alert(self, body: str) -> tuple[int, str]:
        """Alert number and a short rule description from the PR body's alert link."""
        match = ALERT_URL.search(body or "")
        if not match:
            raise ConformError("PR body does not link a code-scanning alert")
        number = int(match.group(1))
        code, out = self.gh(["api", f"repos/{self.repo}/code-scanning/alerts/{number}"])
        if code != 0:
            return number, "code scanning alert"
        data = json.loads(out)
        rule = data.get("rule") or {}
        desc = rule.get("description") or rule.get("id") or "code scanning alert"
        path = ((data.get("most_recent_instance") or {}).get("location") or {}).get("path")
        return number, f"{desc} ({path})" if path else str(desc)

    def ensure_issue(self, alert: int, rule: str, pr: int) -> tuple[int, bool]:
        prefix = f"Code scanning alert #{alert}:"
        found = self._json(
            [
                "issue", "list", "--repo", self.repo, "--state", "all",
                "--search", f'"{prefix}" in:title', "--json", "number,title,state",
            ]
        )  # fmt: skip
        for issue in found:
            if str(issue.get("title", "")).startswith(prefix):
                return int(issue["number"]), False
        body = (
            f"Tracking issue for Copilot Autofix PR #{pr}, created automatically (#83).\n\n"
            f"## Goal\nResolve code-scanning alert #{alert}: {rule}.\n\n"
            f"## Plan\nReview the Autofix change in #{pr}; CI and the issue/changelog "
            "checks must pass before merge.\n\nLane: lane:core\n"
        )
        args = ["issue", "create", "--repo", self.repo, "--title", f"{prefix} {rule}",
                "--body", body, "--assignee", MAINTAINER]  # fmt: skip
        for label in ISSUE_LABELS:
            args += ["--label", label]
        url = self._ok(args).strip().splitlines()[-1]
        return int(url.rstrip("/").rsplit("/", 1)[-1]), True

    def ensure_link_and_base(self, pr: dict[str, Any], issue: int, result: Result) -> None:
        number = str(pr["number"])
        if pr.get("baseRefName") != BASE:
            self._ok(["pr", "edit", number, "--repo", self.repo, "--base", BASE])
            result.actions.append(f"retargeted to `{BASE}`")
        body = str(pr.get("body") or "")
        if issue not in {int(n) for n in CLOSES.findall(body)}:
            new_body = f"Closes #{issue}\n\n{body}".rstrip() + "\n"
            self._ok(["pr", "edit", number, "--repo", self.repo, "--body", new_body])
            result.actions.append(f"linked `Closes #{issue}`")

    def ensure_fragment(
        self, branch: str, issue: int, alert: int, rule: str, result: Result
    ) -> None:
        path = f"changelog.d/{issue}.security.md"
        code, _ = self.gh(["api", f"repos/{self.repo}/contents/{path}?ref={branch}"])
        if code == 0:
            return
        text = f"Fix code-scanning alert #{alert}: {rule}.\n"
        self._ok(
            [
                "api", "-X", "PUT", f"repos/{self.repo}/contents/{path}",
                "-f", f"message=Add changelog fragment for #{issue} (autofix conformance)",
                "-f", f"content={base64.b64encode(text.encode()).decode()}",
                "-f", f"branch={branch}",
            ]
        )  # fmt: skip
        result.actions.append(f"added `{path}`")

    def rerun_checks(self, pr: dict[str, Any], result: Result) -> None:
        number, branch = str(pr["number"]), str(pr["headRefName"])
        labels = {str(lb.get("name")) for lb in pr.get("labels") or []}
        if ADOPTION_LABEL in labels:
            self.gh(["pr", "edit", number, "--repo", self.repo, "--remove-label", ADOPTION_LABEL])
            result.actions.append(f"removed `{ADOPTION_LABEL}`")
        for workflow, inputs in DISPATCH:
            args = ["workflow", "run", workflow, "--repo", self.repo, "--ref", branch]
            if "pr" in inputs:
                args += ["-f", f"pr={number}"]
            self._ok(args)
        result.actions.append("re-ran CI, CodeQL, Changelog, and Issue policy checks")

    def comment(self, pr: int, result: Result) -> None:
        lines = "\n".join(f"- {a}" for a in result.actions)
        body = (
            f"{MARKER}\nMade this Copilot Autofix PR follow the repo's procedures "
            f"(AGENTS.md, Automated PRs; #83). Tracking issue: #{result.issue}.\n\n{lines}\n\n"
            "Merging still waits for green checks (cloud routine or maintainer)."
        )
        self._ok(["pr", "comment", str(pr), "--repo", self.repo, "--body", body])

    def conform(self, number: int) -> Result:
        pr = self.load_pr(number)
        alert, rule = self.alert(str(pr.get("body") or ""))
        result = Result(number)
        result.issue, created = self.ensure_issue(alert, rule, number)
        result.actions.append(
            f"{'created' if created else 'reused'} tracking issue #{result.issue}"
        )
        self.ensure_link_and_base(pr, result.issue, result)
        self.ensure_fragment(str(pr["headRefName"]), result.issue, alert, rule, result)
        self.rerun_checks(pr, result)
        self.comment(number, result)
        return result


def main(argv: Sequence[str] | None = None, gh: Gh = run_gh) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or not args[0].isdigit():
        print("usage: autofix_conform.py <pr-number>", file=sys.stderr)
        return 2
    repo = os.environ.get("GITHUB_REPOSITORY", "Reid-n0rc/n1mm-scope-bridge")
    try:
        result = Conformer(repo, gh).conform(int(args[0]))
    except ConformError as err:
        print(f"::notice::Not conformed: {err}")
        return 0
    print(f"PR #{result.pr} conformed: " + "; ".join(result.actions))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
