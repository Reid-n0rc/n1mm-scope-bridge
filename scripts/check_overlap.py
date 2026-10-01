# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Find file overlaps between an issue's plan (or a PR) and the open PRs (issue #43).

Before starting an issue, check that its **Files** list does not overlap the
files changed by any open PR (AGENTS.md, Parallel work):

    python scripts/check_overlap.py 30          # exit 1 if issue #30 overlaps an open PR

In CI, warn when a PR touches files another open PR also changes:

    python scripts/check_overlap.py --pr 52     # GitHub warning annotations, always exit 0

Standard library plus the ``gh`` CLI (authenticated through GH_TOKEN in CI).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence

Gh = Callable[[Sequence[str]], str]

_FILES_SECTION = re.compile(r"^##\s+Files\s*$(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)
_BACKTICK = re.compile(r"`([^`\s]+)`")
_BRACES = re.compile(r"\{([^{}]*)\}")


def run_gh(args: Sequence[str]) -> str:  # pragma: no cover - real process
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def expand_braces(pattern: str) -> list[str]:
    """``a/{b,c}.py`` -> ``["a/b.py", "a/c.py"]`` (nested and repeated groups too)."""
    match = _BRACES.search(pattern)
    if match is None:
        return [pattern]
    head, tail = pattern[: match.start()], pattern[match.end() :]
    return [p for option in match.group(1).split(",") for p in expand_braces(head + option + tail)]


def looks_like_path(token: str) -> bool:
    return ("/" in token or "." in token) and not token.startswith(("-", "http"))


def files_from_issue(body: str) -> list[str]:
    """Paths and globs named in backticks in the issue's ``## Files`` section."""
    section = _FILES_SECTION.search(body or "")
    if section is None:
        return []
    paths: list[str] = []
    for token in _BACKTICK.findall(section.group(1)):
        for path in expand_braces(token.strip().rstrip(",;:")):
            if looks_like_path(path) and path not in paths:
                paths.append(path)
    return paths


def matches(planned: str, changed: str) -> bool:
    """True if a planned path, directory, or glob covers a changed file."""
    planned = planned.rstrip("/")
    if planned == changed or changed.startswith(planned + "/"):
        return True
    return any(ch in planned for ch in "*?[") and fnmatch.fnmatch(changed, planned)


def overlap(planned: Iterable[str], changed: Iterable[str]) -> list[str]:
    changed = list(changed)
    hits = {c for p in planned for c in changed if matches(p, c)}
    return sorted(hits)


def open_prs(gh: Gh) -> dict[int, dict[str, object]]:
    data = json.loads(
        gh(["pr", "list", "--state", "open", "--json", "number,title,files", "--limit", "100"])
    )
    return {
        int(pr["number"]): {
            "title": pr["title"],
            "files": [f["path"] for f in pr.get("files") or []],
        }
        for pr in data
    }


def issue_report(
    issue: int, body: str, prs: Mapping[int, Mapping[str, object]]
) -> tuple[list[str], bool]:
    planned = files_from_issue(body)
    if not planned:
        return [f"#{issue}: no `## Files` section with backticked paths; cannot check."], True
    lines, clash = [], False
    for number, pr in sorted(prs.items()):
        hits = overlap(planned, pr["files"])  # type: ignore[arg-type]
        if hits:
            clash = True
            lines.append(f"#{issue} overlaps PR #{number} ({pr['title']}): {', '.join(hits)}")
    if not clash:
        lines.append(f"#{issue}: no overlap with {len(prs)} open PR(s). Clear to start.")
    return lines, clash


def pr_report(number: int, prs: Mapping[int, Mapping[str, object]]) -> list[str]:
    mine = prs.get(number)
    if mine is None:
        return [f"PR #{number} is not open."]
    lines = []
    for other, pr in sorted(prs.items()):
        if other == number:
            continue
        hits = overlap(mine["files"], pr["files"])  # type: ignore[arg-type]
        if hits:
            lines.append(
                f"::warning::PR #{number} and PR #{other} ({pr['title']}) both change: "
                f"{', '.join(hits)}. Merge one first, then merge dev into the other (AGENTS.md)."
            )
    return lines or [f"PR #{number}: no file overlap with other open PRs."]


def main(argv: Sequence[str] | None = None, *, gh: Gh = run_gh) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("issue", nargs="?", type=int, help="issue number to check before starting")
    group.add_argument("--pr", type=int, help="PR number to check (CI; warnings only)")
    args = parser.parse_args(argv)
    prs = open_prs(gh)
    if args.pr is not None:
        print("\n".join(pr_report(args.pr, prs)))
        return 0
    body = json.loads(gh(["issue", "view", str(args.issue), "--json", "body"]))["body"]
    lines, clash = issue_report(args.issue, body, prs)
    print("\n".join(lines))
    return 1 if clash else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
