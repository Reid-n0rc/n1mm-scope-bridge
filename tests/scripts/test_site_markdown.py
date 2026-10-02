# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from pathlib import Path

import pytest
import site_markdown as md

ROOT = Path(__file__).resolve().parent.parent.parent
BASE = "https://github.com/o/r/blob/dev"
links = md.doc_link_mapper(BASE, "docs/user")


def test_headings_paragraphs_and_title_dropped() -> None:
    out = md.render("# Title\n\nIntro *text* here\nwraps.\n\n## Center scope mode\n\nMore.", links)
    assert "Title" not in out
    assert "<p>Intro <em>text</em> here wraps.</p>" in out
    assert '<h2 id="center-scope-mode">Center scope mode</h2>' in out


def test_second_h1_is_rejected() -> None:
    with pytest.raises(md.MarkdownError, match="first heading"):
        md.render("## A\n\n# B", links)


def test_table_with_inline_formatting() -> None:
    out = md.render(
        "| Message | Fix |\n|---|---|\n"
        "| `Could not <open>` | Use **this** or <https://ftdichip.com/x> |",
        links,
    )
    assert "<th>Message</th>" in out
    assert "<td><code>Could not &lt;open&gt;</code></td>" in out
    assert "<strong>this</strong>" in out
    assert '<a href="https://ftdichip.com/x">https://ftdichip.com/x</a>' in out


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("| a | b |\n| c | d |", "separator"),
        ("| a | b |\n|---|---|\n| c |", "cells"),
        ("| a | b |\n|---|---|\n| c | d", "start and end"),
        ("![img](x.png)", "unsupported"),
        ("<div>raw</div>", "unsupported"),
        ("```\ncode", "unclosed"),
        ("- one\nnot indented", "unexpected line"),
    ],
)
def test_unsupported_or_malformed_input_fails(text: str, message: str) -> None:
    with pytest.raises(md.MarkdownError, match=message):
        md.render(text, links)


def test_lists_with_continuations() -> None:
    out = md.render("1. First\n   continues\n2. Second\n\n- a\n- b", links)
    assert "<ol><li>First continues</li><li>Second</li></ol>" in out
    assert "<ul><li>a</li><li>b</li></ul>" in out


def test_quote_and_code_block() -> None:
    out = md.render("> Keep **streaming**?\n> really\n\n```\na < b\n```", links)
    assert "<blockquote><p>Keep <strong>streaming</strong>? really</p></blockquote>" in out
    assert "<pre><code>a &lt; b</code></pre>" in out


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("settings.md", f"{BASE}/docs/user/settings.md"),
        ("../n1mm-setup.md#x", f"{BASE}/docs/n1mm-setup.md#x"),
        ("https://example.com/a", "https://example.com/a"),
        ("#local", "#local"),
    ],
)
def test_link_mapping(target: str, expected: str) -> None:
    assert links(target) == expected


def test_link_outside_repo_rejected() -> None:
    with pytest.raises(md.MarkdownError, match="outside"):
        links("../../../etc/passwd")


def test_real_user_docs_render() -> None:
    for name in ("troubleshooting.md", "settings.md", "gui.md", "udp-control.md"):
        path = ROOT / "docs" / "user" / name
        if path.exists():
            assert "<" in md.render(path.read_text(encoding="utf-8"), links), name
