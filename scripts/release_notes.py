# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Release helpers for the tag-triggered release workflow (#46).

    python scripts/release_notes.py meta --tag v0.1.0-rc1           # version/prerelease outputs
    python scripts/release_notes.py stamp --version 0.1.0rc1        # stamp the build's version
    python scripts/release_notes.py notes --tag v0.1.0-rc1 --out notes.md [--report FILE]
    python scripts/release_notes.py sums --out SHA256SUMS FILE...
    python scripts/release_notes.py merge --existing OLD.md --new NEW.md --out BODY.md [--replace]

Releases carry exactly ONE asset, the universal installer; every other build
output stays on the workflow run. The complete corresponding source (GPLv3 s.6)
is GitHub's automatic "Source code" archives on the same release page.

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
    info: TagInfo,
    changelog: str,
    report: str | None = None,
    *,
    dry_run: bool = False,
    installer_sha256: str | None = None,
    run_url: str | None = None,
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
    files = [
        FILES_START,
        "## Download\n\n"
        f"- **`{installer_name(v)}`**: one installer for all Windows PCs. It picks the "
        "right version for your PC: 64-bit (x64), Windows on ARM, or 32-bit (command line "
        "only). FTDI's LibFT4222 is not included; the installer can download FTDI's "
        "signed DLLs for you.",
    ]
    verify = ["## Verify"]
    if installer_sha256:
        verify.append(f"SHA-256 of `{installer_name(v)}`:\n\n```\n{installer_sha256}\n```")
    verify.append(
        "Build provenance: `gh attestation verify "
        f"{installer_name(v)} --repo Reid-n0rc/n1mm-scope-bridge`"
    )
    if run_url:
        verify.append(
            f"The regression report, portable zips, wheel and screenshots are on the "
            f"[release build run]({run_url}) (workflow artifacts)."
        )
    files.append("\n\n".join(verify))
    files.append(
        "## Source\n\nComplete corresponding source (GPLv3): the **Source code** "
        "archives below, generated by GitHub from this release's tag."
    )
    files.append(FILES_END)
    parts.append("\n\n".join(files))
    if report:
        parts.append(
            "<details><summary>Release regression report</summary>\n\n"
            + report.strip()
            + "\n\n</details>"
        )
    return "\n\n".join(parts) + "\n"


SCREENSHOTS_ZIP = "screenshots.zip"
REGRESSION_REPORT = "regression-report.md"
FILES_START = "<!-- release-files -->"
FILES_END = "<!-- /release-files -->"


def installer_name(version: str) -> str:
    return f"n1mm-scope-bridge-setup-{version}.exe"


def required_assets(version: str) -> list[str]:
    """The release carries exactly these files: the universal installer only."""
    return [installer_name(version)]


def missing_assets(version: str, present: Sequence[str]) -> list[str]:
    """Required release files not in ``present`` (file names)."""
    have = set(present)
    return [name for name in required_assets(version) if name not in have]


def extra_assets(version: str, present: Sequence[str]) -> list[str]:
    """Files in ``present`` that must not be release assets."""
    allowed = set(required_assets(version))
    return sorted(name for name in present if name not in allowed)


def merge_notes(existing: str, new: str, *, replace: bool) -> str:
    """Keep the maintainer's own notes and refresh our release-files section.

    ``replace`` (a release this workflow wrote itself) swaps the whole body.
    Otherwise any previous release-files section is removed and the new
    section (``new`` is expected to contain it) is appended.
    """
    if replace or not existing.strip():
        return new
    kept = re.sub(
        re.escape(FILES_START) + r".*?" + re.escape(FILES_END), "", existing, flags=re.S
    ).rstrip()
    start = new.find(FILES_START)
    section = new[start:] if start >= 0 else new
    return f"{kept}\n\n{section.strip()}\n"


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


def _parser() -> argparse.ArgumentParser:
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
    notes.add_argument("--installer", type=Path, help="installer file, for its SHA-256")
    notes.add_argument("--run-url", help="link to the build run with the other outputs")
    merge = sub.add_parser("merge", help="refresh our section in an existing release body")
    merge.add_argument("--existing", type=Path, required=True)
    merge.add_argument("--new", type=Path, required=True)
    merge.add_argument("--out", type=Path, required=True)
    merge.add_argument("--replace", action="store_true", help="the body is ours; replace it")
    assets = sub.add_parser("assets", help="fail unless the dir holds exactly the release files")
    assets.add_argument("--tag", required=True)
    assets.add_argument("dir", type=Path)
    sums = sub.add_parser("sums", help="write SHA256SUMS")
    sums.add_argument("--out", type=Path, required=True)
    sums.add_argument("files", nargs="+", type=Path)
    return parser


def _notes(args: argparse.Namespace) -> None:
    report = (
        args.report.read_text(encoding="utf-8") if args.report and args.report.exists() else None
    )
    digest = hashlib.sha256(args.installer.read_bytes()).hexdigest() if args.installer else None
    text = release_notes(
        parse_tag(args.tag),
        args.changelog.read_text(encoding="utf-8"),
        report,
        dry_run=args.dry_run,
        installer_sha256=digest,
        run_url=args.run_url,
    )
    args.out.write_text(text, encoding="utf-8")


def _assets(args: argparse.Namespace) -> None:
    version = parse_tag(args.tag).package_version
    names = [p.name for p in args.dir.iterdir() if p.is_file()]
    missing = missing_assets(version, names)
    if missing:
        raise ReleaseError(f"release is missing required files: {', '.join(missing)}")
    extra = extra_assets(version, names)
    if extra:
        raise ReleaseError(f"only the installer may be released; remove: {', '.join(extra)}")
    print(f"release files OK: {', '.join(required_assets(version))}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
            _notes(args)
        elif args.command == "merge":
            existing = args.existing.read_text(encoding="utf-8")
            new = args.new.read_text(encoding="utf-8")
            text = merge_notes(existing, new, replace=args.replace)
            args.out.write_text(text, encoding="utf-8")
        elif args.command == "assets":
            _assets(args)
        else:
            args.out.write_text(sha256sums(args.files), encoding="utf-8")
    except (ReleaseError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
