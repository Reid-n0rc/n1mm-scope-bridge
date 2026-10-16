# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Close the issues a merged pull request links, when it merges into dev (#220, #250).

GitHub closes ``Closes #n`` issues only on a merge into the default branch
(``master``). Work merges into ``dev``, so the ``Close linked issues``
workflow runs this after each merge into ``dev``:

    python scripts/close_linked_issues.py <PR number> [owner/repo]

GitHub's own parse (``closingIssuesReferences``) is empty for PRs whose base
is not the default branch, so this parses the closing keywords itself
(``close``, ``fix`` and ``resolve`` in every tense, any case, then ``#n`` or
``owner/repo#n`` for this repo). The PR is read through the API, never from
the event payload, and its body is only matched against a pattern.

Safety: a PR that is not merged, or not based on ``dev``, closes nothing.
Only open issues in this repo are closed, never pull requests. More than
``MAX_ISSUES`` references fail the run before anything is closed. Any API
error fails the run. Only numbers are logged.

Accepted risk: the body is read when the run starts, seconds after the
merge, so an edit after the merge could change what closes. Only the
maintainer and agents can edit PR bodies here, and the REST API offers no
simple body-as-of-merge.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any

DEFAULT_REPO = "Reid-n0rc/n1mm-scope-bridge"
BASE_BRANCH = "dev"
MAX_ISSUES = 10

REPO_RE = re.compile(r"[\w.-]+/[\w.-]+")
# GitHub's closing-keyword grammar: keyword, then a colon and/or whitespace,
# then "#n" or "owner/repo#n".
CLOSING_RE = re.compile(
    r"(?<![\w/-])(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)(?::\s*|\s+)"
    r"(?:(?P<repo>[\w.-]+/[\w.-]+))?#(?P<number>\d+)(?![\w-])",
    re.IGNORECASE,
)

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


def closing_issues(body: str, repo: str) -> list[int]:
    """Issue numbers that ``body`` closes in ``repo``, in order, deduplicated."""
    numbers: list[int] = []
    for match in CLOSING_RE.finditer(body):
        ref_repo = match.group("repo")
        if ref_repo is not None and ref_repo.lower() != repo.lower():
            continue
        number = int(match.group("number"))
        if number > 0 and number not in numbers:
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
    data = gh_json(gh, ["api", f"repos/{repo}/pulls/{pr}"])
    if data.get("merged") is not True:
        return [f"PR #{pr} is not merged; nothing to close."]
    base = (data.get("base") or {}).get("ref")
    if base != BASE_BRANCH:
        return [f"PR #{pr} is not based on {BASE_BRANCH!r}; nothing to close."]
    sha = str(data.get("merge_commit_sha") or "")
    if not sha:
        raise RuntimeError(f"PR #{pr} has no merge commit")
    body = data.get("body") or ""
    if not isinstance(body, str):
        raise RuntimeError(f"PR #{pr} has a malformed body")
    issues = closing_issues(body, repo)
    if not issues:
        return [f"PR #{pr} links no issues; nothing to close."]
    if len(issues) > MAX_ISSUES:
        raise RuntimeError(
            f"PR #{pr} references {len(issues)} issues, more than {MAX_ISSUES}; closing none"
        )
    log: list[str] = []
    for issue in issues:
        info = gh_json(gh, ["api", f"repos/{repo}/issues/{issue}"])
        if "pull_request" in info:
            log.append(f"#{issue}: a pull request, skipped.")
            continue
        if info.get("state") != "open":
            log.append(f"#{issue}: not open, skipped.")
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
    if (
        len(args) not in (1, 2)
        or not args[0].isdigit()
        or (len(args) == 2 and not REPO_RE.fullmatch(args[1]))
    ):
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
