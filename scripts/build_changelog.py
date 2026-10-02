# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Changelog fragments (#45): every PR adds a file instead of editing CHANGELOG.md.

Fragments live in ``changelog.d/<issue>.<type>.md`` where type is one of
added, changed, deprecated, removed, fixed, security (Keep a Changelog).

    python scripts/build_changelog.py --preview            # the Unreleased section
    python scripts/build_changelog.py --version 0.2.0      # release PR only: fold and delete
    python scripts/build_changelog.py --check-pr FILES...  # CI: does this PR add a fragment?

Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRAGMENTS = ROOT / "changelog.d"
CHANGELOG = ROOT / "CHANGELOG.md"
TYPES = ("added", "changed", "deprecated", "removed", "fixed", "security")
NO_CHANGELOG_LABEL = "no-changelog"
_NAME = re.compile(r"^(?P<issue>\d+)\.(?P<type>[a-z]+)(?:\.\d+)?\.md$")
_UNRELEASED = re.compile(
    r"^## \[Unreleased\]\n(?P<body>.*?)(?=^## \[|\Z)", re.MULTILINE | re.DOTALL
)


class FragmentError(ValueError):
    """A fragment file is misnamed or empty."""


@dataclass(frozen=True)
class Fragment:
    issue: int
    kind: str
    text: str
    path: Path


def parse_fragment(path: Path) -> Fragment:
    match = _NAME.match(path.name)
    if match is None or match["type"] not in TYPES:
        raise FragmentError(
            f"{path.name}: name it <issue>.<type>.md with type one of {', '.join(TYPES)}"
        )
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise FragmentError(f"{path.name} is empty")
    return Fragment(int(match["issue"]), match["type"], text, path)


def load_fragments(directory: Path = FRAGMENTS) -> list[Fragment]:
    return sorted(
        (parse_fragment(p) for p in directory.glob("*.md") if p.name != "README.md"),
        key=lambda f: (TYPES.index(f.kind), f.issue, f.path.name),
    )


def _bullet(fragment: Fragment) -> str:
    text = fragment.text.removeprefix("- ")
    lines = text.splitlines()
    first = f"- {lines[0]} (#{fragment.issue})"
    return "\n".join([first, *("  " + line.strip() for line in lines[1:])])


def render(fragments: Sequence[Fragment]) -> str:
    """Keep a Changelog sections (### Added, …) for the given fragments."""
    out: list[str] = []
    for kind in TYPES:
        entries = [_bullet(f) for f in fragments if f.kind == kind]
        if entries:
            out += [f"### {kind.capitalize()}", "", *entries, ""]
    return "\n".join(out)


def release(changelog: str, fragments: Sequence[Fragment], version: str, date: str) -> str:
    """CHANGELOG text with a new ``## [version] - date`` section built from fragments."""
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\d+)?", version):
        raise FragmentError(f"version {version!r} must look like 1.2.3 or 1.2.3-rc1")
    if not fragments:
        raise FragmentError("no changelog fragments to release")
    match = _UNRELEASED.search(changelog)
    if match is None:
        raise FragmentError("CHANGELOG.md has no '## [Unreleased]' section")
    section = f"## [{version}] - {date}\n\n{render(fragments)}"
    head = changelog[: match.start("body")]
    rest = changelog[match.end("body") :]
    return f"{head}\nSee `changelog.d/` for changes not yet released.\n\n{section}\n{rest}".replace(
        "\n\n\n", "\n\n"
    )


def check_pr(changed: Sequence[str], labels: Sequence[str]) -> list[str]:
    """Problems with a PR's changelog fragments (empty list means OK)."""
    if NO_CHANGELOG_LABEL in labels:
        return []
    added = [c for c in changed if c.startswith("changelog.d/") and c != "changelog.d/README.md"]
    if not added:
        return [
            "Add a changelog fragment changelog.d/<issue>.<type>.md (see changelog.d/README.md), "
            f"or label the PR '{NO_CHANGELOG_LABEL}'."
        ]
    problems = []
    for name in added:
        match = _NAME.match(Path(name).name)
        if match is None or match["type"] not in TYPES:
            problems.append(f"{name}: name it <issue>.<type>.md ({', '.join(TYPES)})")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true", help="print the Unreleased entries")
    mode.add_argument("--version", help="fold fragments into CHANGELOG.md as this version")
    mode.add_argument("--check-pr", nargs="*", metavar="FILE", help="files changed by the PR")
    parser.add_argument("--label", action="append", default=[], help="PR label (repeatable)")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--fragments", type=Path, default=FRAGMENTS)
    parser.add_argument("--changelog", type=Path, default=CHANGELOG)
    args = parser.parse_args(argv)
    try:
        if args.check_pr is not None:
            problems = check_pr(args.check_pr, args.label)
            for p in problems:
                print(f"::error::{p}")
            return 1 if problems else 0
        fragments = load_fragments(args.fragments)
        if args.preview:
            print(render(fragments) or "(no unreleased changes)")
            return 0
        text = release(
            args.changelog.read_text(encoding="utf-8"), fragments, args.version, args.date
        )
        args.changelog.write_text(text, encoding="utf-8")
        for f in fragments:
            f.path.unlink()
        print(f"CHANGELOG.md: added {args.version} with {len(fragments)} entries")
        return 0
    except FragmentError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
