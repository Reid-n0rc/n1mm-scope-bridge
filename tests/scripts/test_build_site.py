# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from pathlib import Path

import build_site as bs
import pytest

RELEASE = bs.context("v1.2.3", "2026-11-01")
DEV = bs.context(None, None)


def write_site(root: Path, pages: dict[str, str], partials: dict[str, str] | None = None) -> Path:
    (root / bs.PARTIALS).mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "assets" / "style.css").write_text("body{}", encoding="utf-8")
    for name, text in pages.items():
        (root / name).write_text(text, encoding="utf-8")
    for name, text in (partials or {}).items():
        (root / bs.PARTIALS / f"{name}.html").write_text(text, encoding="utf-8")
    return root


# --- context ---------------------------------------------------------------------------


def test_release_context() -> None:
    assert RELEASE["version"] == "1.2.3"
    assert RELEASE["release_url"].endswith("/releases/tag/v1.2.3")
    assert RELEASE["docs_url"].endswith("/tree/v1.2.3/docs/user")
    assert RELEASE["ref"] == "v1.2.3"


def test_dev_context_has_no_version() -> None:
    assert "version" not in DEV
    assert DEV["ref"] == "dev"


@pytest.mark.parametrize(
    ("tag", "date", "message"),
    [
        ("v1.2.3-rc1", "2026-11-01", "final releases only"),
        ("1.2.3", "2026-11-01", "look like v1.2.3"),
        ("v1.2.3", None, "release-date"),
        ("v1.2.3", "Nov 1", "release-date"),
        (None, "2026-11-01", "needs --tag"),
    ],
)
def test_context_validation(tag: str | None, date: str | None, message: str) -> None:
    with pytest.raises(bs.SiteError, match=message):
        bs.context(tag, date)


# --- render ----------------------------------------------------------------------------


def test_render_blocks_includes_and_placeholders() -> None:
    text = (
        "<!-- include:nav -->|<!-- if:release -->R {{version}}<!-- endif:release -->"
        "|<!-- if:prerelease -->DEV<!-- endif:prerelease -->"
    )
    partials = {"nav": "NAV {{source_url}}"}
    assert bs.render(text, RELEASE, partials, name="p") == f"NAV {bs.REPO_URL}|R 1.2.3|"
    assert bs.render(text, DEV, partials, name="p") == f"NAV {bs.REPO_URL}||DEV"


def test_multiline_blocks() -> None:
    text = "a<!-- if:prerelease -->\nline1\nline2\n<!-- endif:prerelease -->b"
    assert bs.render(text, RELEASE, {}, name="p") == "ab"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("<!-- include:missing -->", "unknown partial"),
        ("{{version}}", "no value"),
        ("<!-- if:release -->x", "unbalanced"),
        (
            "<!-- if:release --><!-- if:prerelease -->x"
            "<!-- endif:prerelease --><!-- endif:release -->",
            "unbalanced or nested",
        ),
    ],
)
def test_render_errors(text: str, message: str) -> None:
    with pytest.raises(bs.SiteError, match=message):
        bs.render(text, DEV, {}, name="p")


# --- link check and build -------------------------------------------------------------------


def test_check_site_finds_problems(tmp_path: Path) -> None:
    (tmp_path / "a.html").write_text(
        '<a href="b.html#top">x</a><a href="b.html#nope">y</a><a href="gone.html">z</a>'
        '<a href="#here">h</a><h2 id="here"></h2><img src="i.png"><a href="https://x.org/">e</a>',
        encoding="utf-8",
    )
    (tmp_path / "b.html").write_text('<h1 id="top">B</h1>', encoding="utf-8")
    problems = bs.check_site(tmp_path)
    assert any("missing anchor 'b.html#nope'" in p for p in problems)
    assert any("broken link 'gone.html'" in p for p in problems)
    assert any("without alt text" in p for p in problems)
    assert any("broken link 'i.png'" in p for p in problems)
    assert len(problems) == 4


def test_build_renders_pages_and_copies_assets(tmp_path: Path) -> None:
    src = write_site(
        tmp_path / "src",
        {
            "index.html": "<!-- include:head -->"
            '<a href="index.html#top">{{source_url}}</a><p id="top">'
        },
        {"head": '<link rel="stylesheet" href="assets/style.css">'},
    )
    out = tmp_path / "out"
    (out / "stale").mkdir(parents=True)
    written = bs.build(out, DEV, src)
    assert [p.name for p in written] == ["index.html"]
    assert (out / "assets" / "style.css").exists()
    assert (out / ".nojekyll").exists()
    assert not (out / bs.PARTIALS).exists()
    assert not (out / "stale").exists()
    assert bs.REPO_URL in (out / "index.html").read_text(encoding="utf-8")


def test_build_fails_on_broken_link(tmp_path: Path) -> None:
    src = write_site(tmp_path / "src", {"index.html": '<a href="nope.html">x</a>'})
    with pytest.raises(bs.SiteError, match="broken link"):
        bs.build(tmp_path / "out", DEV, src)


def test_build_needs_pages(tmp_path: Path) -> None:
    with pytest.raises(bs.SiteError, match="no pages"):
        bs.build(tmp_path / "out", DEV, write_site(tmp_path / "src", {}))


# --- the real site ------------------------------------------------------------------------


@pytest.mark.parametrize("tag", [None, "v0.1.0"])
def test_real_site_builds_cleanly(tmp_path: Path, tag: str | None) -> None:
    ctx = bs.context(tag, "2026-11-01" if tag else None)
    pages = bs.build(tmp_path / "out", ctx)
    assert {p.name for p in pages} >= {"index.html", "install.html", "n1mm.html", "about.html"}
    text = "".join(p.read_text(encoding="utf-8") for p in pages)
    assert "{{" not in text
    assert "<!-- if:" not in text
    if tag:
        assert "Download 0.1.0 for Windows" in text
        assert "In development." not in text
    else:
        assert "In development." in text
        assert "Download" not in (tmp_path / "out" / "index.html").read_text(encoding="utf-8")


def test_real_site_pages_have_titles_and_language() -> None:
    for page in bs.SITE.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert '<html lang="en">' in text, page.name
        assert "<title>" in text, page.name
        assert '<main id="main"' in text, page.name


def test_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert bs.main(["--out", str(tmp_path / "a")]) == 0
    assert "no release yet" in capsys.readouterr().out
    assert (
        bs.main(["--out", str(tmp_path / "b"), "--tag", "v1.0.0", "--release-date", "2026-11-01"])
        == 0
    )
    assert (
        bs.main(
            ["--out", str(tmp_path / "c"), "--tag", "v1.0.0-rc1", "--release-date", "2026-11-01"]
        )
        == 1
    )
    assert "final releases only" in capsys.readouterr().err
