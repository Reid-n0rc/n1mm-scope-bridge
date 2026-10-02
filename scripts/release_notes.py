# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Release helpers for the tag-triggered release workflow (#46).

    python scripts/release_notes.py meta --tag v0.1.0-rc1           # version/prerelease outputs
    python scripts/release_notes.py stamp --version 0.1.0rc1        # stamp the build's version
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

from build_windows_app import zip_name  # single source of truth for the zip name

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

    @property
    def package_version(self) -> str:
        """The PEP 440 version the build is stamped with: 0.1.0, or 0.1.0rc2 for -rc2.

        The tag is the single source of truth for a release's version, so a tag
        and pyproject.toml can never disagree (the release workflow stamps it).
        """
        return f"{self.version}rc{self.rc}" if self.rc is not None else self.version


def parse_tag(tag: str) -> TagInfo:
    """``v0.1.0`` or ``v0.1.0-rc1``; anything else is rejected."""
    match = _TAG.match(tag.strip())
    if match is None:
        raise ReleaseError(f"tag {tag!r} must look like vX.Y.Z or vX.Y.Z-rcN")
    rc = match["rc"]
    return TagInfo(tag.strip(), match["version"], int(rc) if rc else None)


# Where the version lives in a checkout: (path, regex whose group 1 / 2 surround it).
VERSION_FILES: tuple[tuple[str, str], ...] = (
    ("pyproject.toml", r'(?m)^(version\s*=\s*")[^"]+(")'),
    ("src/n1mm_scope_bridge/__init__.py", r'(?m)^(__version__\s*=\s*")[^"]+(")'),
    ("uv.lock", r'(?m)^(name = "n1mm-scope-bridge"\nversion = ")[^"]+(")'),
)


def stamp_version(root: Path, version: str) -> list[str]:
    """Write ``version`` into every version location under ``root``; returns the files."""
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:rc[1-9]\d*)?", version):
        raise ReleaseError(f"refusing to stamp malformed version {version!r}")
    changed = []
    for rel, pattern in VERSION_FILES:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        new, count = re.subn(pattern, rf"\g<1>{version}\g<2>", text, count=1)
        if count != 1:
            raise ReleaseError(f"no version found in {rel}")
        path.write_text(new, encoding="utf-8")
        changed.append(rel)
    return changed


def project_versions(root: Path) -> dict[str, str]:
    """The version recorded in each version location (they must all agree)."""
    found = {}
    for rel, pattern in VERSION_FILES:
        match = re.search(
            pattern.replace('[^"]+', '([^"]+)'), (root / rel).read_text(encoding="utf-8")
        )
        found[rel] = match[2] if match else ""
    return found


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
MISSING_SECTION = (
    "_CHANGELOG.md has no section for this version. See "
    "[CHANGELOG.md](https://github.com/Reid-n0rc/n1mm-scope-bridge/blob/master/CHANGELOG.md) "
    "and the commits since the previous release._"
)


def release_notes(
    info: TagInfo, changelog: str, report: str | None = None, *, dry_run: bool = False
) -> str:
    """Release body: the CHANGELOG section for the version, plus the regression report.

    A missing section never blocks a release (the maintainer may tag or create a
    release in the GitHub web UI without a changelog PR): the notes say so instead.
    """
    body = changelog_section(changelog, info.version)
    if body is None:
        body = DRY_RUN_PLACEHOLDER if dry_run else MISSING_SECTION
    v = info.package_version
    parts = []
    if info.prerelease:
        parts.append(
            f"**Release candidate {info.rc} for {info.version}.** For on-air testing; "
            "not yet the final release."
        )
    parts += [f"## Changes in {info.version}", body]
    parts.append(
        "## Downloads\n\n"
        "- `n1mm-scope-bridge-setup-*.exe`: **one installer for all Windows PCs** "
        "(recommended). It picks the right version for your PC: 64-bit (x64), "
        "Windows on ARM, or 32-bit (command line only).\n"
        f"- `{zip_name(v, 'x64')}`: portable app, 64-bit Windows (x64)\n"
        f"- `{zip_name(v, 'ARM64')}`: portable app, Windows on ARM (native ARM64)\n"
        f"- `{zip_name(v, 'x86')}`: portable command-line app, 32-bit Windows\n"
        "- `*.whl`: Python wheel; `*.tar.gz`: complete source code (GPLv3 corresponding source)\n"
        f"- `{SCREENSHOTS_ZIP}`: screenshots of this build's GUI and installer\n"
        "- `SHA256SUMS`: checksums for every file\n\n"
        "FTDI's LibFT4222 is not included in any file. The installer can download FTDI's "
        "signed DLLs for you (64-bit and 32-bit); Windows on ARM can use the 64-bit version."
    )
    if report:
        parts.append(
            "<details><summary>Release regression report</summary>\n\n"
            + report.strip()
            + "\n\n</details>"
        )
    return "\n\n".join(parts) + "\n"


SCREENSHOTS_ZIP = "screenshots.zip"
REGRESSION_REPORT = "regression-report.md"


def required_assets(version: str) -> list[str]:
    """Every file a release must carry (SHA256SUMS is added after these)."""
    return [
        f"n1mm-scope-bridge-setup-{version}.exe",
        *(zip_name(version, arch) for arch in ("x64", "ARM64", "x86")),
        f"n1mm_scope_bridge-{version}-py3-none-any.whl",
        f"n1mm_scope_bridge-{version}.tar.gz",
        REGRESSION_REPORT,
        SCREENSHOTS_ZIP,
    ]


def missing_assets(version: str, present: Sequence[str]) -> list[str]:
    """Required release files not in ``present`` (file names)."""
    have = set(present)
    return [name for name in required_assets(version) if name not in have]


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
    stamp = sub.add_parser("stamp", help="write a version into pyproject, __init__ and uv.lock")
    stamp.add_argument("--version", required=True)
    stamp.add_argument("--root", type=Path, default=ROOT)
    notes = sub.add_parser("notes", help="write the release body")
    notes.add_argument("--tag", required=True)
    notes.add_argument("--out", type=Path, required=True)
    notes.add_argument("--report", type=Path)
    notes.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    notes.add_argument(
        "--dry-run", action="store_true", help="allow a missing CHANGELOG section (rehearsals)"
    )
    assets = sub.add_parser("assets", help="fail if a required release file is missing")
    assets.add_argument("--tag", required=True)
    assets.add_argument("dir", type=Path)
    sums = sub.add_parser("sums", help="write SHA256SUMS")
    sums.add_argument("--out", type=Path, required=True)
    sums.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "meta":
            info = parse_tag(args.tag)
            print(f"version={info.package_version}")
            print(f"base_version={info.version}")
            print(f"prerelease={'true' if info.prerelease else 'false'}")
        elif args.command == "stamp":
            files = stamp_version(args.root, args.version)
            print(f"stamped {args.version} into {', '.join(files)}")
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
        elif args.command == "assets":
            info = parse_tag(args.tag)
            names = [p.name for p in args.dir.iterdir() if p.is_file()]
            missing = missing_assets(info.package_version, names)
            if missing:
                raise ReleaseError(f"release is missing required files: {', '.join(missing)}")
            print(
                f"all {len(required_assets(info.package_version))} required release files present"
            )
        else:
            args.out.write_text(sha256sums(args.files), encoding="utf-8")
    except (ReleaseError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
