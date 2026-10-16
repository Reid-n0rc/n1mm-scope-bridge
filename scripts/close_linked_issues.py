# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Close the issues a merged pull request links, when it merges into dev (#220, #250).

GitHub closes ``Closes #n`` issues only on a merge into the default branch
(``master``). Work merges into ``dev``, so the ``Close linked issues``
workflow runs this after each merge into ``dev``:

    python scripts/close_linked_issues.py <PR number> [owner/repo]

GitHub's own parse (``closingIssuesReferences``) is empty for PRs whose base
is not the default branch, so this parses the closing keywords itself. The
parser is conservative, so it never matches more than GitHub would: it drops
code blocks, code spans, HTML comments, blockquotes, links and URLs, then
accepts only ``<keyword>[:] #<n>`` or ``<keyword>[:] <this repo>#<n>`` in
plain ASCII (keywords: close, fix and resolve in every tense, any case).

Every fact comes from the API (never the event payload), and the body is only
matched against patterns. Nothing closes unless all of these hold:

- the PR is merged, based on ``dev``, opened from this repo (not a fork), and
  its author is an owner, member or collaborator;
- the PR body was not edited after the merge (GraphQL ``lastEditedAt``);
- the PR references no more than ``MAX_ISSUES`` issues (more fails the run);
- each issue is an open issue in this repo (not a PR), has ``plan-approved``
  and an assignee, and its timeline shows this PR referencing it before the
  merge (``cross-referenced`` event).

Any API error fails the run. Only numbers are logged.

Residual risk: an issue the PR mentioned before the merge (anywhere in it)
could be closed by a ``Closes`` line added in the seconds between the body
check and the close. Only trusted authors' PRs and approved, assigned issues
are in scope, so the worst case is closing a live issue early, which is
visible and reversible.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

DEFAULT_REPO = "Reid-n0rc/n1mm-scope-bridge"
BASE_BRANCH = "dev"
MAX_ISSUES = 10
MAX_TIMELINE_PAGES = 10
PAGE_SIZE = 100
APPROVED_LABEL = "plan-approved"
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
EDITED_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name)"
    "{pullRequest(number:$number){lastEditedAt}}}"
)

REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.ASCII)

# Constructs whose text GitHub does not treat as closing references (or might
# not): stripped before matching, so the parser errs towards closing nothing.
HTML_COMMENT_RE = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
FENCE_RE = re.compile(
    r"^ {0,3}(?P<fence>`{3,}|~{3,}).*?(?:^ {0,3}(?P=fence)[`~]*[ \t]*$|\Z)",
    re.DOTALL | re.MULTILINE,
)
QUOTE_OR_INDENT_RE = re.compile(r"^(?: {0,3}>| {4}|[ ]{0,3}\t).*$", re.MULTILINE)
CODE_SPAN_RE = re.compile(r"(?P<ticks>`+).+?(?P=ticks)", re.DOTALL)
LINK_RE = re.compile(r"!?\[[^\]]*\](?:\([^)]*\)|\[[^\]]*\])?")
AUTOLINK_RE = re.compile(r"<[^>\s]*>")
URL_RE = re.compile(r"\b(?:https?|ftp)://\S*|\bwww\.\S*", re.IGNORECASE)

# ASCII only, so full-width "#", non-ASCII digits and case-folded lookalikes
# (such as the long s) never match.
CLOSING_RE = re.compile(
    r"(?:^|(?<=[\s(*_]))(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):? "
    r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<number>[0-9]+)"
    r"(?=$|[\s.,;:!?)*_])",
    re.IGNORECASE | re.ASCII,
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


def plain_text(body: str) -> str:
    """``body`` without the Markdown constructs whose references must not count."""
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = HTML_COMMENT_RE.sub(" ", text)
    text = FENCE_RE.sub("\n", text)
    text = QUOTE_OR_INDENT_RE.sub("", text)
    text = CODE_SPAN_RE.sub(" ", text)
    text = LINK_RE.sub(" ", text)
    text = AUTOLINK_RE.sub(" ", text)
    return URL_RE.sub(" ", text)


def closing_issues(body: str, repo: str) -> list[int]:
    """Issue numbers that ``body`` closes in ``repo``, in order, deduplicated."""
    numbers: list[int] = []
    for match in CLOSING_RE.finditer(plain_text(body)):
        ref_repo = match.group("repo")
        if ref_repo is not None and ref_repo.lower() != repo.lower():
            continue
        number = int(match.group("number"))
        if number > 0 and number not in numbers:
            numbers.append(number)
    return numbers


def timestamp(value: Any, what: str) -> datetime:
    """Parse a GitHub ISO 8601 timestamp, failing closed."""
    if not isinstance(value, str):
        raise RuntimeError(f"{what} is missing")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise RuntimeError(f"{what} is malformed") from err


def edited_after(gh: Gh, pr: int, repo: str, merged_at: datetime) -> bool:
    """True if the PR body was edited after ``merged_at``."""
    owner, _, name = repo.partition("/")
    data = gh_json(
        gh,
        [
            "api",
            "graphql",
            "-f",
            f"query={EDITED_QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={pr}",
        ],
    )
    pull = data["data"]["repository"]["pullRequest"]
    edited = pull["lastEditedAt"]
    return edited is not None and timestamp(edited, "lastEditedAt") > merged_at


def referenced_before(gh: Gh, issue: int, pr: int, repo: str, merged_at: datetime) -> bool:
    """True if the issue's timeline shows ``pr`` referencing it before ``merged_at``."""
    for page in range(1, MAX_TIMELINE_PAGES + 1):
        events = gh_json(
            gh, ["api", f"repos/{repo}/issues/{issue}/timeline?per_page={PAGE_SIZE}&page={page}"]
        )
        if not isinstance(events, list):
            raise RuntimeError(f"#{issue}: malformed timeline")
        for event in events:
            if event.get("event") != "cross-referenced":
                continue
            source = (event.get("source") or {}).get("issue") or {}
            source_repo = str((source.get("repository") or {}).get("full_name", ""))
            if (
                source.get("number") == pr
                and source.get("pull_request")
                and source_repo.lower() == repo.lower()
                and timestamp(event.get("created_at"), "event time") <= merged_at
            ):
                return True
        if len(events) < PAGE_SIZE:
            return False
    raise RuntimeError(f"#{issue}: timeline longer than {MAX_TIMELINE_PAGES} pages")


def issue_problem(info: Mapping[str, Any]) -> str | None:
    """Why an issue must not be closed, or None if it may be."""
    if "pull_request" in info:
        return "a pull request"
    if info.get("state") != "open":
        return "not open"
    labels = {str(label.get("name")) for label in info.get("labels") or []}
    if APPROVED_LABEL not in labels:
        return f"no {APPROVED_LABEL}"
    if not info.get("assignees"):
        return "no assignee"
    return None


def close_comment(pr: int, sha: str) -> str:
    """The comment left on each closed issue."""
    return (
        f"Closed by #{pr} (merged into {BASE_BRANCH} as {sha[:7]}). "
        "Ships in the next release from master."
    )


def close_linked(pr: int, repo: str, gh: Gh) -> list[str]:
    """Close the PR's eligible linked issues; return one log line per issue."""
    data = gh_json(gh, ["api", f"repos/{repo}/pulls/{pr}"])
    if data.get("merged") is not True:
        return [f"PR #{pr} is not merged; nothing to close."]
    if (data.get("base") or {}).get("ref") != BASE_BRANCH:
        return [f"PR #{pr} is not based on {BASE_BRANCH!r}; nothing to close."]
    head_repo = str(((data.get("head") or {}).get("repo") or {}).get("full_name", ""))
    if head_repo.lower() != repo.lower():
        return [f"PR #{pr} comes from a fork; nothing to close."]
    if data.get("author_association") not in TRUSTED_ASSOCIATIONS:
        return [f"PR #{pr} author is not a collaborator; nothing to close."]
    sha = str(data.get("merge_commit_sha") or "")
    if not sha:
        raise RuntimeError(f"PR #{pr} has no merge commit")
    merged_at = timestamp(data.get("merged_at"), "merged_at")
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
    if edited_after(gh, pr, repo, merged_at):
        raise RuntimeError(f"PR #{pr} body was edited after the merge; closing none")
    log: list[str] = []
    for issue in issues:
        problem = issue_problem(gh_json(gh, ["api", f"repos/{repo}/issues/{issue}"]))
        if problem is None and not referenced_before(gh, issue, pr, repo, merged_at):
            problem = "not referenced before the merge"
        if problem is not None:
            log.append(f"#{issue}: {problem}, skipped.")
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
        or not re.fullmatch(r"[0-9]{1,9}", args[0])
        or (len(args) == 2 and not REPO_RE.fullmatch(args[1]))
    ):
        print("usage: close_linked_issues.py <PR number> [owner/repo]", file=sys.stderr)
        return 2
    pr = int(args[0])
    repo = args[1] if len(args) == 2 else DEFAULT_REPO
    try:
        log = close_linked(pr, repo, gh)
    except (RuntimeError, AttributeError, TypeError, KeyError) as err:
        print(f"error: could not close the issues linked by PR #{pr}: {err}", file=sys.stderr)
        return 1
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
