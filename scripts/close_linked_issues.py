# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Close the issues a merged pull request links, when it merges into dev (issue #220).

GitHub closes ``Closes #n`` issues only on a merge into the default branch
(``master``). Work merges into ``dev``, so the ``Close linked issues``
workflow runs this after each merge into ``dev``:

    python scripts/close_linked_issues.py <PR number> [owner/repo]

It reads GitHub's own parse of the closing keywords
(``closingIssuesReferences``), keeps same-repo issues that are still open, and
closes each as completed with a comment naming the PR and merge commit. A PR
that is not merged, or not based on ``dev``, closes nothing. Only issue
numbers are logged. Standard library plus ``gh``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

DEFAULT_REPO = "Reid-n0rc/n1mm-scope-bridge"
BASE_BRANCH = "dev"
PR_FIELDS = "closingIssuesReferences,mergeCommit,baseRefName,state"

Gh = Callable[[Sequence[str]], str]


def gh_run(args: Sequence[str]) -> str:  # pragma: no cover - real gh process
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False, errors="replace"
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def gh_json(gh: Gh, args: Sequence[str]) -> Any:
    """Run ``gh`` and parse its JSON output."""
    try:
        return json.loads(gh(args) or "null")
    except json.JSONDecodeError as err:
        raise RuntimeError(f"gh {' '.join(args[:2])} returned invalid JSON: {err}") from err


def same_repo_issues(refs: Sequence[Mapping[str, Any]], repo: str) -> list[int]:
    """Issue numbers from ``closingIssuesReferences`` that live in ``repo``, deduplicated."""
    owner, _, name = repo.partition("/")
    numbers: list[int] = []
    for ref in refs:
        ref_repo = ref.get("repository") or {}
        ref_owner = (ref_repo.get("owner") or {}).get("login", "")
        if ref_owner.lower() != owner.lower() or str(ref_repo.get("name", "")).lower() != (
            name.lower()
        ):
            continue
        number = ref.get("number")
        if isinstance(number, int) and number not in numbers:
            numbers.append(number)
    return numbers


def close_comment(pr: int, sha: str) -> str:
    """The comment left on each closed issue."""
    return (
        f"Closed by #{pr} (merged into {BASE_BRANCH} as {sha[:7]}). "
        "Ships in the next release from master."
    )


def close_linked(pr: int, repo: str, gh: Gh) -> list[str]:
    """Close the PR's open same-repo linked issues; return one log line per issue."""
    data = gh_json(gh, ["pr", "view", str(pr), "--repo", repo, "--json", PR_FIELDS])
    if data.get("state") != "MERGED":
        return [f"PR #{pr} is not merged; nothing to close."]
    if data.get("baseRefName") != BASE_BRANCH:
        return [f"PR #{pr} merged into {data.get('baseRefName')!r}, not {BASE_BRANCH!r}."]
    sha = str((data.get("mergeCommit") or {}).get("oid", ""))
    if not sha:
        raise RuntimeError(f"PR #{pr} has no merge commit")
    issues = same_repo_issues(data.get("closingIssuesReferences") or [], repo)
    if not issues:
        return [f"PR #{pr} links no issues in {repo}; nothing to close."]
    log: list[str] = []
    for issue in issues:
        state = gh_json(gh, ["issue", "view", str(issue), "--repo", repo, "--json", "state"])
        if state.get("state") != "OPEN":
            log.append(f"#{issue}: already closed, skipped.")
            continue
        gh(
            [
                "issue",
                "close",
                str(issue),
                "--repo",
                repo,
                "--reason",
                "completed",
                "--comment",
                close_comment(pr, sha),
            ]
        )
        log.append(f"#{issue}: closed.")
    return log


def main(argv: Sequence[str] | None = None, gh: Gh = gh_run) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in (1, 2) or not args[0].isdigit():
        print("usage: close_linked_issues.py <PR number> [owner/repo]", file=sys.stderr)
        return 2
    pr = int(args[0])
    repo = args[1] if len(args) == 2 else DEFAULT_REPO
    try:
        log = close_linked(pr, repo, gh)
    except (RuntimeError, AttributeError, TypeError) as err:
        print(f"error: could not close the issues linked by PR #{pr}: {err}", file=sys.stderr)
        return 1
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
