# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Release helpers for the tag-triggered release workflow (#46).

    python scripts/release_notes.py meta --tag v0.1.0-rc1           # version/prerelease outputs
    python scripts/release_notes.py notes --tag v0.1.0-rc1 --out notes.md [--report FILE]
    python scripts/release_notes.py sums --out SHA256SUMS FILE...

Standard library only. Never creates tags or releases itself.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TAG = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)(?:-rc(?P<rc>[1-9]\d*))?$")
_SECTION = r"^## \[{name}\][^\n]*\n(?P<body>.*?)(?=^## \[|\Z)"


class ReleaseError(ValueError):
    """The tag, changelog, or project version is not releasable."""


@dataclass(frozen=True)
class TagInfo:
    tag: str
    version: str
    """The release version without the -rcN suffix, for example 0.1.0."""
    rc: int | None

    @property
    def prerelease(self) -> bool:
        return self.rc is not None


def parse_tag(tag: str) -> TagInfo:
    """``v0.1.0`` or ``v0.1.0-rc1``; anything else is rejected."""
    match = _TAG.match(tag.strip())
    if match is None:
        raise ReleaseError(f"tag {tag!r} must look like vX.Y.Z or vX.Y.Z-rcN")
    rc = match["rc"]
    return TagInfo(tag.strip(), match["version"], int(rc) if rc else None)


def check_project_version(info: TagInfo, pyproject: str) -> None:
    """The tag must match pyproject.toml's version (agents never bump versions)."""
    match = re.search(
        r'^\[project\][^\[]*?^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE | re.DOTALL
    )
    if match is None:
        raise ReleaseError("pyproject.toml has no [project] version")
    version = match[1]
    if version != info.version:
        raise ReleaseError(
            f"tag {info.tag} does not match pyproject.toml version {version}; "
            "the release PR sets the version"
        )


def changelog_section(changelog: str, version: str) -> str | None:
    """The body of ``## [version]`` (any suffix such as a date), or None."""
    match = re.search(_SECTION.format(name=re.escape(version)), changelog, re.MULTILINE | re.DOTALL)
    if match is None:
        return None
    return match["body"].strip() or None


DRY_RUN_PLACEHOLDER = (
    "_Dry run: CHANGELOG.md has no section for this version yet. The release PR "
    "creates it with `python scripts/build_changelog.py --version X.Y.Z`._"
)


def release_notes(
    info: TagInfo, changelog: str, report: str | None = None, *, dry_run: bool = False
) -> str:
    """Release body: the CHANGELOG section for the version, plus the regression report.

    A missing section is an error, except in a dry run, which uses a placeholder.
    """
    body = changelog_section(changelog, info.version)
    if body is None and dry_run:
        body = DRY_RUN_PLACEHOLDER
    if body is None:
        raise ReleaseError(
            f"CHANGELOG.md has no '## [{info.version}]' section; the release PR runs "
            f"`python scripts/build_changelog.py --version {info.version}`"
        )
    parts = []
    if info.prerelease:
        parts.append(
            f"**Release candidate {info.rc} for {info.version}.** For on-air testing; "
            "not yet the final release."
        )
    parts += [f"## Changes in {info.version}", body]
    parts.append(
        "## Downloads\n\n"
        "- `n1mm-scope-bridge-setup-*.exe`: Windows installer (recommended)\n"
        "- `n1mm-scope-bridge-*-windows.zip`: portable Windows app\n"
        "- `*.whl`: Python wheel; `*.tar.gz`: complete source code (GPLv3 corresponding source)\n"
        "- `SHA256SUMS`: checksums for every file\n\n"
        "FTDI's LibFT4222 is not included; the installer links to FTDI's download page."
    )
    if report:
        parts.append(
            "<details><summary>Release regression report</summary>\n\n"
            + report.strip()
            + "\n\n</details>"
        )
    return "\n\n".join(parts) + "\n"


def sha256sums(paths: Sequence[Path]) -> str:
    """``sha256sum``-compatible lines, sorted by file name."""
    if not paths:
        raise ReleaseError("no files to checksum")
    names = [p.name for p in paths]
    if len(set(names)) != len(names):
        raise ReleaseError(f"duplicate file names: {sorted(names)}")
    lines = []
    for path in sorted(paths, key=lambda p: p.name):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release helpers (#46)")
    sub = parser.add_subparsers(dest="command", required=True)
    meta = sub.add_parser("meta", help="print version and prerelease as KEY=VALUE lines")
    meta.add_argument("--tag", required=True)
    notes = sub.add_parser("notes", help="write the release body")
    notes.add_argument("--tag", required=True)
    notes.add_argument("--out", type=Path, required=True)
    notes.add_argument("--report", type=Path)
    notes.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    notes.add_argument(
        "--dry-run", action="store_true", help="allow a missing CHANGELOG section (rehearsals)"
    )
    sums = sub.add_parser("sums", help="write SHA256SUMS")
    sums.add_argument("--out", type=Path, required=True)
    sums.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "meta":
            info = parse_tag(args.tag)
            check_project_version(info, (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
            print(f"version={info.version}")
            print(f"prerelease={'true' if info.prerelease else 'false'}")
        elif args.command == "notes":
            info = parse_tag(args.tag)
            report = (
                args.report.read_text(encoding="utf-8")
                if args.report and args.report.exists()
                else None
            )
            text = release_notes(
                info, args.changelog.read_text(encoding="utf-8"), report, dry_run=args.dry_run
            )
            args.out.write_text(text, encoding="utf-8")
        else:
            args.out.write_text(sha256sums(args.files), encoding="utf-8")
    except (ReleaseError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
