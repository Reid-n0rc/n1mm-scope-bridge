# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Render the Markdown subset used in docs/user/ into HTML for the website (#23).

The website shows user docs (for example troubleshooting.md) by rendering the
file itself at build time, so the site can never disagree with the docs.
Anything outside the supported subset raises ``MarkdownError`` and fails the
site build, instead of being shown wrong.

Supported: ``##``/``###`` headings (a leading ``#`` title is dropped, the page
has its own), paragraphs, ``-`` and ``1.`` lists with indented continuation
lines, pipe tables, ``>`` quotes, fenced code, and inline `` `code` ``,
``**bold**``, ``*italic*``, ``[text](url)`` and ``<https://…>`` links.
"""

from __future__ import annotations

import html
import posixpath
import re
from collections.abc import Callable

LinkMapper = Callable[[str], str]

HEADING = re.compile(r"^(#{1,3}) (.+)$")
ORDERED = re.compile(r"^\d+\. (.*)$")
INLINE_CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
AUTOLINK = re.compile(r"&lt;(https?://[^\s&]+)&gt;")
UNSUPPORTED = re.compile(r"!\[|<(?!https?://)[a-zA-Z/!]")


class MarkdownError(ValueError):
    """The document uses Markdown the site renderer doesn't support."""


def slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def doc_link_mapper(base_url: str, doc_dir: str) -> LinkMapper:
    """Map links in a doc: other repo files go to GitHub (``base_url``); URLs and
    anchors stay as they are. ``doc_dir`` is the doc's folder in the repo."""

    def mapper(target: str) -> str:
        if re.match(r"^(https?:|mailto:|#)", target):
            return target
        path, _, frag = target.partition("#")
        resolved = posixpath.normpath(posixpath.join(doc_dir, path))
        if resolved.startswith(".."):
            raise MarkdownError(f"link {target!r} points outside the repository")
        return f"{base_url}/{resolved}" + (f"#{frag}" if frag else "")

    return mapper


def inline(text: str, links: LinkMapper) -> str:
    if UNSUPPORTED.search(INLINE_CODE.sub("", text)):
        raise MarkdownError(f"unsupported Markdown or HTML in: {text!r}")
    codes: list[str] = []

    def keep_code(m: re.Match[str]) -> str:
        codes.append(f"<code>{html.escape(m.group(1), quote=False)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    out = INLINE_CODE.sub(keep_code, text)
    out = html.escape(out, quote=False)
    out = AUTOLINK.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', out)
    out = LINK.sub(lambda m: f'<a href="{html.escape(links(m.group(2)))}">{m.group(1)}</a>', out)
    out = BOLD.sub(r"<strong>\1</strong>", out)
    out = ITALIC.sub(r"<em>\1</em>", out)
    return re.sub("\x00(\\d+)\x00", lambda m: codes[int(m.group(1))], out)


def _cells(line: str) -> list[str]:
    row = line.strip()
    if not (row.startswith("|") and row.endswith("|")):
        raise MarkdownError(f"table row must start and end with '|': {line!r}")
    return [c.strip() for c in row[1:-1].split("|")]


def _table(lines: list[str], links: LinkMapper) -> str:
    if len(lines) < 2 or not re.fullmatch(r"\|(\s*:?-{3,}:?\s*\|)+", lines[1].replace(" ", "")):
        raise MarkdownError(f"table needs a header and a |---| separator row: {lines[0]!r}")
    head = _cells(lines[0])
    body = [_cells(line) for line in lines[2:]]
    for row in body:
        if len(row) != len(head):
            raise MarkdownError(f"table row has {len(row)} cells, header has {len(head)}: {row}")
    thead = "".join(f"<th>{inline(c, links)}</th>" for c in head)
    rows = "".join(
        "<tr>" + "".join(f"<td>{inline(c, links)}</td>" for c in row) + "</tr>" for row in body
    )
    table = f"<table><thead><tr>{thead}</tr></thead><tbody>{rows}</tbody></table>"
    return f'<div class="table-wrap">{table}</div>'


def _list(lines: list[str], ordered: bool, links: LinkMapper) -> str:
    items: list[str] = []
    for line in lines:
        m = ORDERED.match(line) if ordered else re.match(r"^- (.*)$", line)
        if m:
            items.append(m.group(1))
        elif line.startswith("  ") and items:
            items[-1] += " " + line.strip()
        else:
            raise MarkdownError(f"unexpected line in list: {line!r}")
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{inline(i, links)}</li>" for i in items) + f"</{tag}>"


def _block(block: list[str], links: LinkMapper) -> str:
    """One run of non-blank lines: a table, a list, a quote, or a paragraph."""
    if block[0].startswith("|"):
        return _table(block, links)
    if ORDERED.match(block[0]):
        return _list(block, True, links)
    if block[0].startswith("- "):
        return _list(block, False, links)
    if block[0].startswith(">"):
        quoted = " ".join(b.lstrip(">").strip() for b in block)
        return f"<blockquote><p>{inline(quoted, links)}</p></blockquote>"
    return f"<p>{inline(' '.join(b.strip() for b in block), links)}</p>"


def _code(lines: list[str], i: int) -> tuple[str, int]:
    end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("```")), None)
    if end is None:
        raise MarkdownError("unclosed ``` code block")
    return (
        f"<pre><code>{html.escape(chr(10).join(lines[i + 1 : end]), quote=False)}</code></pre>",
        end + 1,
    )


def _heading(m: re.Match[str], first: bool, links: LinkMapper) -> str:
    level = len(m.group(1))
    if level == 1:
        if not first:
            raise MarkdownError("only the first heading may be a '#' title")
        return ""
    content = inline(m.group(2), links)
    return f'<h{level} id="{slug(content)}">{content}</h{level}>'


def render(text: str, links: LinkMapper) -> str:
    """Render ``text`` (the supported subset) to HTML."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    first = True
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            code, i = _code(lines, i)
            out.append(code)
        elif m := HEADING.match(line):
            out.append(_heading(m, first, links))
            i += 1
        else:
            block = []
            while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "```")):
                block.append(lines[i])
                i += 1
            out.append(_block(block, links))
        first = False
    return "\n".join(part for part in out if part)
