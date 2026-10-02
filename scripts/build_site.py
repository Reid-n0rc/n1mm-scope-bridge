# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Build the GitHub Pages site from ``site/`` (issue #21).

The site describes the **latest release** only. Pass the release tag and the
site shows that version and its downloads; with no tag it builds the
"in development" site used until the first release. Standard library only.

    python scripts/build_site.py --out _site                      # no release yet
    python scripts/build_site.py --out _site --tag v0.1.0 --release-date 2026-11-01

Template syntax:
  <!-- include:NAME -->                      site/_partials/NAME.html
  <!-- if:release --> ... <!-- endif:release -->        only when --tag is given
  <!-- if:prerelease --> ... <!-- endif:prerelease -->  only without --tag
  {{name}}                                   a value from the build context
  <!-- screenshot:NAME -->                   a GUI screenshot from --screenshots DIR
  <!-- markdown:docs/user/NAME.md -->        that user doc, rendered (site_markdown.py)
                                             (manifest.json written by
                                             `n1mm-scope-bridge gui --screenshot DIR`)
"""

from __future__ import annotations

import argparse
import html
import html.parser
import json
import posixpath
import re
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

import site_markdown

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
REPO_URL = "https://github.com/Reid-n0rc/n1mm-scope-bridge"
PARTIALS = "_partials"
TAG = re.compile(r"^v\d+\.\d+\.\d+$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INCLUDE = re.compile(r"<!-- include:([a-z0-9_-]+) -->")
BLOCK = re.compile(r"<!-- if:(release|prerelease) -->(.*?)<!-- endif:\1 -->", re.S)
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
SCREENSHOT = re.compile(r"<!-- screenshot:([a-z0-9-]+) -->")
# <!-- markdown:docs/user/NAME.md --> renders that doc (#23), so the page matches it.
MARKDOWN = re.compile(r"<!-- markdown:(docs/user/[a-z0-9_-]+\.md) -->")
SHOTS_DIR = "assets/screenshots"
PREVIEW_LABEL = "Development preview"


class SiteError(Exception):
    """The site could not be built correctly."""


def context(tag: str | None, release_date: str | None) -> dict[str, str]:
    """Values available to templates. ``tag`` None means no release yet."""
    if tag is None:
        if release_date is not None:
            raise SiteError("--release-date needs --tag")
        return {"source_url": REPO_URL, "ref": "dev", "docs_url": f"{REPO_URL}/tree/dev/docs/user"}
    if not TAG.match(tag):
        raise SiteError(f"release tag must look like v1.2.3 (final releases only), got {tag!r}")
    if release_date is None or not DATE.match(release_date):
        raise SiteError("a release needs --release-date YYYY-MM-DD")
    return {
        "source_url": REPO_URL,
        "ref": tag,
        "version": tag[1:],
        "release_date": release_date,
        "release_url": f"{REPO_URL}/releases/tag/{tag}",
        "docs_url": f"{REPO_URL}/tree/{tag}/docs/user",
    }


Shots = dict[str, dict[str, object]]


def load_screenshots(directory: Path) -> Shots:
    """Read ``manifest.json`` from a ``gui --screenshot`` run and check its files."""
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise SiteError(f"screenshots: cannot read {directory / 'manifest.json'}: {err}") from None
    if not isinstance(manifest, dict) or not manifest:
        raise SiteError("screenshots: manifest.json lists no screenshots")
    for scene, entry in manifest.items():
        for key in ("file", "width", "height", "alt", "caption"):
            if not isinstance(entry, dict) or key not in entry:
                raise SiteError(f"screenshots: {scene!r} has no {key!r}")
        for key in ("file", "dark"):
            if key in entry and not (directory / str(entry[key])).is_file():
                raise SiteError(f"screenshots: {scene!r} file {entry[key]!r} is missing")
    return manifest


def figure(scene: str, entry: dict[str, object], *, preview: bool) -> str:
    """Accessible <figure> for one screenshot (explicit size; dark variant if any)."""
    src = f"{SHOTS_DIR}/{entry['file']}"
    dark = (
        f'<source srcset="{SHOTS_DIR}/{entry["dark"]}" media="(prefers-color-scheme: dark)">'
        if "dark" in entry
        else ""
    )
    label = f' <span class="badge">{PREVIEW_LABEL}</span>' if preview else ""
    return (
        f'<figure class="screenshot" id="shot-{scene}"><picture>{dark}'
        f'<img src="{src}" alt="{html.escape(str(entry["alt"]))}" '
        f'width="{int(str(entry["width"]))}" height="{int(str(entry["height"]))}" loading="lazy">'
        f"</picture><figcaption>{html.escape(str(entry['caption']))}{label}</figcaption></figure>"
    )


def render(
    text: str,
    ctx: dict[str, str],
    partials: dict[str, str],
    *,
    name: str,
    shots: Shots | None = None,
) -> str:
    def include(m: re.Match[str]) -> str:
        if m.group(1) not in partials:
            raise SiteError(f"{name}: unknown partial {m.group(1)!r}")
        return partials[m.group(1)]

    text = INCLUDE.sub(include, text)

    def markdown(m: re.Match[str]) -> str:
        path = ROOT / m.group(1)
        if not path.is_file():
            raise SiteError(f"{name}: {m.group(1)} does not exist")
        base = f"{ctx['source_url']}/blob/{ctx['ref']}"
        links = site_markdown.doc_link_mapper(base, posixpath.dirname(m.group(1)))
        try:
            return site_markdown.render(path.read_text(encoding="utf-8"), links)
        except site_markdown.MarkdownError as err:
            raise SiteError(f"{name}: {m.group(1)}: {err}") from None

    text = MARKDOWN.sub(markdown, text)

    def screenshot(m: re.Match[str]) -> str:
        if shots is None:
            return ""  # built without --screenshots (local preview)
        if m.group(1) not in shots:
            raise SiteError(f"{name}: no screenshot {m.group(1)!r} in the manifest")
        return figure(m.group(1), shots[m.group(1)], preview="version" not in ctx)

    text = SCREENSHOT.sub(screenshot, text)
    released = "version" in ctx

    def block(m: re.Match[str]) -> str:
        if "<!-- if:" in m.group(2):
            raise SiteError(f"{name}: unbalanced or nested if/endif block")
        return m.group(2) if (m.group(1) == "release") == released else ""

    text = BLOCK.sub(block, text)
    if "<!-- if:" in text or "<!-- endif:" in text:
        raise SiteError(f"{name}: unbalanced or nested if/endif block")

    def value(m: re.Match[str]) -> str:
        if m.group(1) not in ctx:
            raise SiteError(f"{name}: no value for {{{{{m.group(1)}}}}}")
        return ctx[m.group(1)]

    return PLACEHOLDER.sub(value, text)


class _Links(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.ids: set[str] = set()
        self.images_without_alt = 0
        self.images_without_size = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"] or "")
        for key in ("href", "src", "srcset"):
            if a.get(key):
                self.refs.append(a[key] or "")
        if tag == "img" and a.get("alt") is None:
            self.images_without_alt += 1
        if tag == "img" and (not a.get("width") or not a.get("height")):
            self.images_without_size += 1


def check_site(out: Path) -> list[str]:
    """Broken internal links or anchors, and images without alt text."""
    pages: dict[str, _Links] = {}
    for page in sorted(out.glob("*.html")):
        parser = _Links()
        parser.feed(page.read_text(encoding="utf-8"))
        pages[page.name] = parser
    problems = []
    for name, parsed in pages.items():
        if parsed.images_without_alt:
            problems.append(f"{name}: {parsed.images_without_alt} image(s) without alt text")
        if parsed.images_without_size:
            problems.append(f"{name}: {parsed.images_without_size} image(s) without width/height")
        for ref in parsed.refs:
            parts = urlsplit(ref)
            if parts.scheme or parts.netloc:
                continue
            target = parts.path or name
            if not (out / target).exists():
                problems.append(f"{name}: broken link {ref!r}")
            elif parts.fragment and target.endswith(".html"):
                ids = pages[target].ids if target in pages else set()
                if parts.fragment not in ids:
                    problems.append(f"{name}: missing anchor {ref!r}")
    return problems


def build(
    out: Path, ctx: dict[str, str], src: Path = SITE, screenshots: Path | None = None
) -> list[Path]:
    """Render every page into ``out`` (replaced), copy assets, and check links."""
    partials = {p.stem: p.read_text(encoding="utf-8") for p in (src / PARTIALS).glob("*.html")}
    shots = load_screenshots(screenshots) if screenshots is not None else None
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out, ignore=shutil.ignore_patterns(PARTIALS, "*.html"))
    if screenshots is not None and shots is not None:
        (out / SHOTS_DIR).mkdir(parents=True, exist_ok=True)
        for entry in shots.values():
            for key in ("file", "dark"):
                if key in entry:
                    shutil.copy2(screenshots / str(entry[key]), out / SHOTS_DIR / str(entry[key]))
    pages = sorted(src.glob("*.html"))
    if not pages:
        raise SiteError(f"no pages in {src}")
    written = []
    for page in pages:
        target = out / page.name
        target.write_text(
            render(page.read_text(encoding="utf-8"), ctx, partials, name=page.name, shots=shots),
            encoding="utf-8",
        )
        written.append(target)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    problems = check_site(out)
    if problems:
        raise SiteError("site check failed:\n" + "\n".join(problems))
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the GitHub Pages site.")
    parser.add_argument("--out", type=Path, default=ROOT / "_site")
    parser.add_argument("--tag", help="final release tag (vX.Y.Z); omit before the first release")
    parser.add_argument("--release-date", help="release date, YYYY-MM-DD (with --tag)")
    parser.add_argument(
        "--screenshots",
        type=Path,
        help="folder from `n1mm-scope-bridge gui --screenshot DIR` (omit: no screenshots)",
    )
    args = parser.parse_args(argv)
    try:
        pages = build(args.out, context(args.tag, args.release_date), screenshots=args.screenshots)
    except SiteError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    what = f"release {args.tag}" if args.tag else "in-development site (no release yet)"
    print(f"Built {len(pages)} pages into {args.out} for {what}.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
