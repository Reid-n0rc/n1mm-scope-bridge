# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Merge gate: is this pull request safe to merge? (issue #97)

PRs into ``dev`` merge with ``gh pr merge <PR> --auto --merge`` (#218).
Auto-merge waits only for the checks the ``dev`` ruleset requires, and
path-filtered workflows are not required, so AGENTS.md requires this gate
to pass, after every check has finished, before enabling auto-merge or
merging any other way:

    python scripts/ready_to_merge.py <PR number>

Exit 0 only when ALL of these hold:

a. every check run and commit status on the PR head finished successfully
   (success, skipped, or neutral; nothing failed, cancelled, pending, or
   waiting for action);
b. no open code-scanning (CodeQL) alerts on ``refs/pull/<PR>/merge``, of any
   severity: fix them, or dismiss genuine false positives with a written
   justification;
c. no open secret-scanning alerts in the repository;
d. the dependency review check, when present, passed (part of a, reported
   separately so the reason is obvious);
e. the PR is open, not a draft, mergeable (no conflicts), and closes an
   approved, assigned issue (release PRs dev -> master of this repository are
   exempt).

Linked issues get exactly the Issue policy check's hardened rules (#247, #256),
by reusing ``check_issue_policy``: each one is read through GitHub's GraphQL
API (``ISSUE_QUERY``), must be an open Issue (not a PR) of this repository
with the same number, and its labels and assignees count only when GitHub
reports the complete list with non-empty names. Every linked issue must pass,
and any error or unexpected data makes the PR not ready (fail closed).

Otherwise it prints every reason and exits 1. Standard library plus ``gh``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from check_issue_policy import (
    ISSUE_QUERY,
    PR_NUMBER,
    REPO_NAME,
    IssueInfo,
    is_release_pr,
    linked_issues,
    parse_issue_node,
    policy_problems,
)

OK_CONCLUSIONS = {"success", "skipped", "neutral"}
DEPENDENCY_REVIEW = "Dependency review"
CODEQL = "CodeQL"
ADVISORY_WHEN_CODEQL_PASSED = ("github-advanced-security",)
# Reduce secret-scanning alerts to their numbers inside gh, so the leaked value
# never enters this process (and can never be logged).
LEAK_ALERT_JQ = "[.[].number]"
PR_FIELDS = ",".join(
    (
        "number", "state", "isDraft", "mergeable", "headRefOid", "body",
        "baseRefName", "headRefName", "isCrossRepository",
    )
)  # fmt: skip

Gh = Callable[[Sequence[str]], Any]


def gh_json(args: Sequence[str]) -> Any:  # pragma: no cover - real gh process
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False, errors="replace"
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {proc.stderr.strip()[:300]}")
    return json.loads(proc.stdout or "null")


def latest_check_runs(runs: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """The most recent run per check name (re-runs replace earlier attempts)."""
    latest: dict[str, Mapping[str, Any]] = {}
    for run in runs:
        name = str(run.get("name", ""))
        if name not in latest or int(run.get("id", 0)) > int(latest[name].get("id", 0)):
            latest[name] = run
    return latest


def advisory_checks(latest: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """Failed checks that do not block, because a stronger check already covered them.

    ``github-advanced-security`` is GitHub's optional Copilot AI security review.
    When it fails (for example because the Copilot quota ran out, HTTP 402) but
    the real ``CodeQL`` code-scanning check passed, it carries no security
    finding: the open-alert check (b) still blocks any CodeQL alert.
    """
    codeql = latest.get(CODEQL)
    if codeql is None or codeql.get("conclusion") != "success":
        return set()
    return {name for name in ADVISORY_WHEN_CODEQL_PASSED if name in latest}


def check_problems(
    runs: Sequence[Mapping[str, Any]],
    statuses: Sequence[Mapping[str, Any]],
    notes: list[str] | None = None,
) -> list[str]:
    """Checks (a) and (d). Advisory skips are appended to ``notes``."""
    problems: list[str] = []
    latest = latest_check_runs(runs)
    advisory = advisory_checks(latest)
    if not latest and not statuses:
        problems.append("no checks have reported on the PR head yet")
    for name, run in sorted(latest.items()):
        status, conclusion = run.get("status"), run.get("conclusion")
        if status != "completed":
            problems.append(f"check '{name}' is {status} (wait for it to finish)")
        elif conclusion not in OK_CONCLUSIONS and name in advisory:
            if notes is not None:
                notes.append(
                    f"advisory check '{name}' concluded {conclusion}; not blocking because "
                    f"'{CODEQL}' passed (open CodeQL alerts are checked separately)"
                )
        elif conclusion not in OK_CONCLUSIONS:
            label = "dependency review" if name == DEPENDENCY_REVIEW else "check"
            problems.append(f"{label} '{name}' concluded {conclusion}")
    for st in statuses:
        state = st.get("state")
        if state != "success":
            problems.append(f"status '{st.get('context')}' is {state}")
    return problems


def code_scanning_problems(alerts: Sequence[Mapping[str, Any]]) -> list[str]:
    """Check (b)."""
    out = []
    for a in alerts:
        rule = a.get("rule") or {}
        loc = (a.get("most_recent_instance") or {}).get("location") or {}
        severity = rule.get("security_severity_level") or rule.get("severity")
        out.append(
            f"open code-scanning alert #{a.get('number')} {rule.get('id')} ({severity}) "
            f"at {loc.get('path')}:{loc.get('start_line')}: fix it, or dismiss a genuine "
            "false positive with a written justification"
        )
    return out


def leak_alert_problems(alert_numbers: Sequence[int]) -> list[str]:
    """Check (c). Only alert numbers reach this script (see ``LEAK_ALERT_JQ``), never
    the leaked value itself, so nothing sensitive can be printed."""
    return [
        f"open secret-scanning alert #{int(n)}: revoke the leaked credential and close "
        "the alert (repository Security tab)"
        for n in alert_numbers
    ]


def fetch_issue(gh: Gh, repo: str, number: int) -> IssueInfo | None:
    """Linked issue ``number`` of ``repo``, read and validated like the Issue policy check.

    Raises on any API error or data the check cannot trust (see
    ``check_issue_policy.parse_issue_node``). None means no such number.
    """
    owner, name = repo.split("/", 1)
    response = gh(
        [
            "api", "graphql",
            "-f", f"query={ISSUE_QUERY}",
            "-f", f"owner={owner}",
            "-f", f"name={name}",
            "-F", f"number={number}",
        ]
    )  # fmt: skip
    return parse_issue_node(response, number, repo)


def release_pr(pr: Mapping[str, Any], repo: str | None = None) -> bool:
    """True for a release PR (dev -> master), from ``gh pr view --json`` output.

    With ``repo``, the head branch must be in that same repository
    (``isCrossRepository`` false), so a fork's branch named ``dev`` is not one.
    """
    head_repo = repo if pr.get("isCrossRepository") is False else None
    as_api = {
        "base": {"ref": pr.get("baseRefName"), "repo": {"full_name": repo}},
        "head": {"ref": pr.get("headRefName"), "repo": {"full_name": head_repo}},
    }
    return is_release_pr(as_api, repo)


def pr_problems(
    pr: Mapping[str, Any], issues: Mapping[int, IssueInfo | None], repo: str | None = None
) -> list[str]:
    """Check (e). ``pr`` is ``gh pr view --json`` output (``repo``: see ``release_pr``)."""
    problems: list[str] = []
    if pr.get("state") != "OPEN":
        problems.append(f"PR is {str(pr.get('state', '')).lower()}, not open")
    if pr.get("isDraft"):
        problems.append("PR is a draft")
    mergeable = pr.get("mergeable")
    if mergeable == "CONFLICTING":
        problems.append("PR has merge conflicts: merge origin/dev into the branch")
    elif mergeable != "MERGEABLE":
        problems.append(f"GitHub has not computed mergeability yet ({mergeable}); retry shortly")
    if not release_pr(pr, repo):
        problems += policy_problems(linked_issues(pr.get("body")), issues)
    return problems


def evaluate(number: int, repo: str, gh: Gh = gh_json, notes: list[str] | None = None) -> list[str]:
    """Every reason the PR is not ready to merge (empty list = ready)."""
    pr = gh(
        [
            "pr", "view", str(number), "--repo", repo, "--json", PR_FIELDS,
        ]
    )  # fmt: skip
    if not isinstance(pr, Mapping) or pr.get("number") != number:
        raise RuntimeError(f"GitHub did not return PR #{number}")
    if not isinstance(pr.get("body"), (str, type(None))):
        raise RuntimeError(f"PR #{number} body is not text")
    sha = pr["headRefOid"]
    runs = gh(["api", f"repos/{repo}/commits/{sha}/check-runs?per_page=100"])["check_runs"]
    statuses = gh(["api", f"repos/{repo}/commits/{sha}/status"]).get("statuses", [])
    code_alerts = gh(
        [
            "api",
            f"repos/{repo}/code-scanning/alerts?ref=refs/pull/{number}/merge&state=open&per_page=100",
        ]
    )
    leak_numbers = gh(
        [
            "api",
            f"repos/{repo}/secret-scanning/alerts?state=open&per_page=100",
            "--jq",
            LEAK_ALERT_JQ,
        ]
    )
    issues: dict[int, IssueInfo | None] = {}
    lookup_problems: list[str] = []
    for n in [] if release_pr(pr, repo) else linked_issues(pr.get("body")):
        try:
            issues[n] = fetch_issue(gh, repo, n)
        except Exception as err:  # fail closed: an unverifiable issue never counts
            issues[n] = None
            lookup_problems.append(f"#{n} could not be verified: {err}")
    return (
        check_problems(runs, statuses, notes)
        + code_scanning_problems(code_alerts or [])
        + leak_alert_problems(leak_numbers or [])
        + pr_problems(pr, issues, repo)
        + lookup_problems
    )


def main(argv: Sequence[str] | None = None, gh: Gh = gh_json) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if (
        len(args) not in (1, 2)
        or not PR_NUMBER.fullmatch(args[0])
        or (len(args) == 2 and not REPO_NAME.fullmatch(args[1]))
    ):
        print("usage: ready_to_merge.py <PR number> [owner/repo]", file=sys.stderr)
        return 2
    number = int(args[0])
    repo = args[1] if len(args) == 2 else "Reid-n0rc/n1mm-scope-bridge"
    notes: list[str] = []
    try:
        problems = evaluate(number, repo, gh, notes)
    except Exception as err:  # fail closed on anything unexpected
        print(f"NOT READY: could not evaluate PR #{number}: {err}")
        return 1
    for note in notes:
        print(f"NOTE: {note}")
    if problems:
        print(f"NOT READY: PR #{number} must not be merged:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"READY: PR #{number} passed every merge-gate check.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
