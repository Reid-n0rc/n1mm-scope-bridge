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
  <!-- screenshots:PREFIX -->                every screenshot named PREFIX-*, or a note
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
# All screenshots whose scene starts with PREFIX-, in manifest (capture) order,
# or a note when the build has none (for example installer pages, which are
# captured on Windows by the release regression and arrive via screenshots.zip).
SCREENSHOT_GROUP = re.compile(r"<!-- screenshots:([a-z0-9]+) -->")
GROUP_FALLBACK = '<p class="note">Screenshots of these steps are added from each release build.</p>'
SHOTS_DIR = "assets/screenshots"
PREVIEW_LABEL = "Development preview"
# Shown on screenshots whose manifest entry says ``"simulated": true`` (emulator
# data, not a real radio), in development and release builds alike.
SIMULATED_LABEL = "Simulated: FT-710 emulator"
# Committed real-radio captures (``gui --screenshot DIR --source radio``, #119).
# Scenes listed in this folder's manifest replace the generated ones.
REAL_DIR = "_real_screenshots"
REAL_LABEL = "Real radio: Yaesu FT-710"
# Screenshots showing spectrum data must say where the data came from.
STREAMING_SCENES = ("main-window", "main-window-live")
# Every file an entry can name (copied into the site and checked to exist).
FILE_KEYS = (
    "file", "dark", "webp", "dark_webp", "still", "dark_still",
    "mp4", "webm", "dark_mp4", "dark_webm",
)  # fmt: skip
VIDEO_TYPES = (("webm", "video/webm"), ("mp4", "video/mp4"))


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
        for key in FILE_KEYS:
            if key in entry and not (directory / str(entry[key])).is_file():
                raise SiteError(f"screenshots: {scene!r} file {entry[key]!r} is missing")
        if entry.get("animated") and "still" not in entry:
            raise SiteError(
                f"screenshots: {scene!r} is animated but has no still image for viewers who "
                "prefer reduced motion"
            )
        if scene in STREAMING_SCENES and not (entry.get("simulated") or entry.get("real_radio")):
            raise SiteError(
                f"screenshots: {scene!r} shows spectrum data but does not state its source "
                '("simulated" or "real_radio")'
            )
    return manifest


def _sources(entry: dict[str, object]) -> str:
    """<source> elements: reduced-motion stills first, then dark, then WebP."""

    def src(key: str, media: str = "", kind: str = "") -> str:
        if key not in entry:
            return ""
        attrs = f' media="{media}"' if media else ""
        attrs += f' type="{kind}"' if kind else ""
        return f'<source srcset="{SHOTS_DIR}/{entry[key]}"{attrs}>'

    if not entry.get("animated"):
        return src("dark", "(prefers-color-scheme: dark)")
    calm = "(prefers-reduced-motion: reduce)"
    dark = "(prefers-color-scheme: dark)"
    return "".join(
        (
            src("dark_still", f"{calm} and {dark}"),
            src("still", calm),
            src("dark_webp", dark, "image/webp"),
            src("dark", dark),
            src("webp", "", "image/webp"),
        )
    )


def _videos(entry: dict[str, object], alt: str, size: str) -> str:
    """<video> elements (light, and dark if recorded) with a GIF fallback inside.

    CSS shows the variant matching the colour scheme and hides all video for
    viewers who prefer reduced motion (they get the still picture instead).
    """
    out = []
    has_dark = any(f"dark_{kind}" in entry for kind, _ in VIDEO_TYPES)
    for prefix, poster_key, gif_key, cls in (
        ("", "still", "file", "motion motion-light" if has_dark else "motion"),
        ("dark_", "dark_still", "dark", "motion motion-dark"),
    ):
        sources = "".join(
            f'<source src="{SHOTS_DIR}/{entry[prefix + kind]}" type="{mime}">'
            for kind, mime in VIDEO_TYPES
            if prefix + kind in entry
        )
        if not sources:
            continue
        poster = f"{SHOTS_DIR}/{entry.get(poster_key, entry['still'])}"
        gif = f"{SHOTS_DIR}/{entry.get(gif_key, entry['file'])}"
        out.append(
            f'<video class="{cls}" autoplay muted loop playsinline preload="auto" '
            f'poster="{poster}" {size} aria-label="{alt}">{sources}'
            f'<img src="{gif}" alt="{alt}" {size}></video>'
        )
    return "".join(out)


def figure(scene: str, entry: dict[str, object], *, preview: bool) -> str:
    """Accessible <figure> for one screenshot or recording (explicit size, variants)."""
    src = f"{SHOTS_DIR}/{entry['file']}"
    label = f' <span class="badge">{PREVIEW_LABEL}</span>' if preview else ""
    if entry.get("simulated"):
        label += f' <span class="badge">{SIMULATED_LABEL}</span>'
    elif entry.get("real_radio"):
        label += f' <span class="badge">{REAL_LABEL}</span>'
    alt = html.escape(str(entry["alt"]))
    size = f'width="{int(str(entry["width"]))}" height="{int(str(entry["height"]))}"'
    caption = f"<figcaption>{html.escape(str(entry['caption']))}{label}</figcaption>"
    if any(kind in entry for kind, _ in VIDEO_TYPES):
        still_dark = (
            f'<source srcset="{SHOTS_DIR}/{entry["dark_still"]}" '
            'media="(prefers-color-scheme: dark)">'
            if "dark_still" in entry
            else ""
        )
        still = (
            f'<picture class="motion-still">{still_dark}'
            f'<img src="{SHOTS_DIR}/{entry["still"]}" alt="{alt}" {size} loading="lazy"></picture>'
        )
        return (
            f'<figure class="screenshot" id="shot-{scene}">{_videos(entry, alt, size)}{still}'
            f"{caption}</figure>"
        )
    return (
        f'<figure class="screenshot" id="shot-{scene}"><picture>{_sources(entry)}'
        f'<img src="{src}" alt="{alt}" {size} loading="lazy"></picture>{caption}</figure>'
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

    def group(m: re.Match[str]) -> str:
        scenes = [k for k in (shots or {}) if k.startswith(m.group(1) + "-")]
        if not scenes or shots is None:
            return GROUP_FALLBACK
        preview = "version" not in ctx
        return (
            '<div class="gallery">'
            + "".join(figure(k, shots[k], preview=preview) for k in scenes)
            + "</div>"
        )

    text = SCREENSHOT_GROUP.sub(group, text)
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


# Tags/attributes that make the browser fetch something (privacy: GDPR, #142).
_RESOURCE_ATTRS = {
    "script": ("src",),
    "img": ("src", "srcset"),
    "source": ("src", "srcset"),
    "video": ("src", "poster"),
    "audio": ("src",),
    "iframe": ("src",),
    "embed": ("src",),
    "object": ("data",),
    "track": ("src",),
}
_LINK_RESOURCE_RELS = {"stylesheet", "icon", "preload", "prefetch", "preconnect", "dns-prefetch",
                       "modulepreload", "manifest", "apple-touch-icon", "mask-icon"}  # fmt: skip
_CSS_EXTERNAL = re.compile(r"(?:url\(\s*['\"]?|@import\s+['\"])\s*(?:https?:)?//", re.IGNORECASE)


def _is_external(ref: str) -> bool:
    ref = ref.strip()
    return any(
        bool(urlsplit(part.strip().split(" ")[0]).netloc)
        or part.strip().lower().startswith(("http:", "https:", "//"))
        for part in ref.split(",")
        if part.strip()
    )


class _Links(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.external_resources: list[str] = []
        self._in_style = False
        self.style_text: list[str] = []
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
        for attr in _RESOURCE_ATTRS.get(tag, ()):
            if a.get(attr) and _is_external(a[attr] or ""):
                self.external_resources.append(f"<{tag} {attr}={a[attr]!r}>")
        rel = set((a.get("rel") or "").lower().split())
        if tag == "link" and rel & _LINK_RESOURCE_RELS and _is_external(a.get("href") or ""):
            self.external_resources.append(f"<link rel={a.get('rel')!r} href={a.get('href')!r}>")
        if a.get("style") and _CSS_EXTERNAL.search(a["style"] or ""):
            self.external_resources.append(f"<{tag} style=...> loads an external URL")
        if tag == "style":
            self._in_style = True
        if tag == "img" and a.get("alt") is None:
            self.images_without_alt += 1
        if tag == "img" and (not a.get("width") or not a.get("height")):
            self.images_without_size += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.style_text.append(data)


def check_privacy(out: Path) -> list[str]:
    """Pages and stylesheets must not load anything from another site (GDPR, #142).

    Third-party fonts, scripts, images or embeds would send visitors' IP addresses
    to someone else. Plain hyperlinks are fine.
    """
    problems = []
    for page in sorted(out.rglob("*.html")):
        parser = _Links()
        parser.feed(page.read_text(encoding="utf-8"))
        name = page.relative_to(out).as_posix()
        problems += [f"{name}: external resource {r}" for r in parser.external_resources]
        if _CSS_EXTERNAL.search("".join(parser.style_text)):
            problems.append(f"{name}: <style> loads an external URL")
    for css in sorted(out.rglob("*.css")):
        if _CSS_EXTERNAL.search(css.read_text(encoding="utf-8")):
            problems.append(f"{css.relative_to(out).as_posix()}: CSS loads an external URL")
    return problems


def check_site(out: Path) -> list[str]:
    """Broken internal links or anchors, images without alt text, third-party loads."""
    pages: dict[str, _Links] = {}
    for page in sorted(out.glob("*.html")):
        parser = _Links()
        parser.feed(page.read_text(encoding="utf-8"))
        pages[page.name] = parser
    problems = check_privacy(out)
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
    origin: dict[str, Path] = {}  # scene -> folder its files come from
    if screenshots is not None and shots is not None:
        origin = dict.fromkeys(shots, screenshots)
        real_dir = src / REAL_DIR
        if (real_dir / "manifest.json").is_file():
            for scene, entry in load_screenshots(real_dir).items():
                shots[scene] = entry
                origin[scene] = real_dir
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out, ignore=shutil.ignore_patterns(PARTIALS, REAL_DIR, "*.html"))
    if shots is not None:
        (out / SHOTS_DIR).mkdir(parents=True, exist_ok=True)
        for scene, entry in shots.items():
            for key in FILE_KEYS:
                if key in entry:
                    name = str(entry[key])
                    shutil.copy2(origin[scene] / name, out / SHOTS_DIR / name)
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
