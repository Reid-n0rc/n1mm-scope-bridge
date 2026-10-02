# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import json
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
    assert any("without width/height" in p for p in problems)
    assert len(problems) == 5


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


# --- screenshots (#68) --------------------------------------------------------------------


def write_shots(directory: Path, *, dark: bool = False, **override: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    entry: dict[str, object] = {
        "file": "main-window.png",
        "width": 720,
        "height": 960,
        "alt": 'The "main" window & status',
        "caption": "The main window.",
    }
    if "real_radio" not in override:
        entry["simulated"] = True  # streaming scenes must state their source
    (directory / "main-window.png").write_bytes(b"png")
    if dark:
        entry["dark"] = "main-window-dark.png"
        (directory / "main-window-dark.png").write_bytes(b"png")
    entry.update(override)
    (directory / "manifest.json").write_text(json.dumps({"main-window": entry}), encoding="utf-8")
    return directory


SHOT_PAGE = {"index.html": "<h1>x</h1><!-- screenshot:main-window -->"}


@pytest.mark.parametrize(("ctx", "preview"), [(DEV, True), (RELEASE, False)])
def test_screenshot_figure_is_accessible(
    tmp_path: Path, ctx: dict[str, str], preview: bool
) -> None:
    out = tmp_path / "out"
    bs.build(out, ctx, write_site(tmp_path / "src", SHOT_PAGE), write_shots(tmp_path / "shots"))
    text = (out / "index.html").read_text(encoding="utf-8")
    assert '<img src="assets/screenshots/main-window.png"' in text
    assert 'alt="The &quot;main&quot; window &amp; status"' in text
    assert 'width="720" height="960"' in text
    assert "<figcaption>The main window." in text
    assert (bs.PREVIEW_LABEL in text) is preview
    assert (out / bs.SHOTS_DIR / "main-window.png").exists()


@pytest.mark.parametrize("ctx", [DEV, RELEASE])
def test_simulated_screenshot_is_labelled(tmp_path: Path, ctx: dict[str, str]) -> None:
    out = tmp_path / "out"
    shots = write_shots(tmp_path / "shots", simulated=True)
    bs.build(out, ctx, write_site(tmp_path / "src", SHOT_PAGE), shots)
    text = (out / "index.html").read_text(encoding="utf-8")
    assert bs.SIMULATED_LABEL in text
    assert "emulator" in text


def test_real_screenshot_is_labelled_real(tmp_path: Path) -> None:
    out = tmp_path / "out"
    shots = write_shots(tmp_path / "shots", real_radio=True)
    bs.build(out, DEV, write_site(tmp_path / "src", SHOT_PAGE), shots)
    text = (out / "index.html").read_text(encoding="utf-8")
    assert bs.SIMULATED_LABEL not in text
    assert bs.REAL_LABEL in text


def test_streaming_screenshot_must_state_its_source(tmp_path: Path) -> None:
    shots = write_shots(tmp_path / "shots", real_radio=False)
    with pytest.raises(bs.SiteError, match="does not state its source"):
        bs.build(tmp_path / "out", DEV, write_site(tmp_path / "src", SHOT_PAGE), shots)


def test_committed_real_screenshots_replace_generated(tmp_path: Path) -> None:
    src = write_site(tmp_path / "src", SHOT_PAGE)
    real = write_shots(src / bs.REAL_DIR, dark=True, real_radio=True, caption="Real FT-710.")
    (real / "main-window.png").write_bytes(b"real-png")
    out = tmp_path / "out"
    bs.build(out, DEV, src, write_shots(tmp_path / "shots"))
    text = (out / "index.html").read_text(encoding="utf-8")
    assert "Real FT-710." in text
    assert bs.REAL_LABEL in text
    assert bs.SIMULATED_LABEL not in text
    assert (out / bs.SHOTS_DIR / "main-window.png").read_bytes() == b"real-png"
    assert (out / bs.SHOTS_DIR / "main-window-dark.png").exists()
    assert not (out / bs.REAL_DIR).exists()  # source folder is not published as-is


def test_real_folder_ignored_without_screenshots(tmp_path: Path) -> None:
    src = write_site(tmp_path / "src", SHOT_PAGE)
    write_shots(src / bs.REAL_DIR, real_radio=True)
    out = tmp_path / "out"
    bs.build(out, DEV, src)
    assert not (out / bs.SHOTS_DIR).exists()


def test_dark_variant_uses_picture_source(tmp_path: Path) -> None:
    out = tmp_path / "out"
    shots = write_shots(tmp_path / "shots", dark=True)
    bs.build(out, DEV, write_site(tmp_path / "src", SHOT_PAGE), shots)
    text = (out / "index.html").read_text(encoding="utf-8")
    assert 'media="(prefers-color-scheme: dark)"' in text
    assert (out / bs.SHOTS_DIR / "main-window-dark.png").exists()


def test_without_screenshots_markers_render_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out"
    bs.build(out, DEV, write_site(tmp_path / "src", SHOT_PAGE))
    assert "<figure" not in (out / "index.html").read_text(encoding="utf-8")


def test_unknown_screenshot_name(tmp_path: Path) -> None:
    src = write_site(tmp_path / "src", {"index.html": "<!-- screenshot:tray-menu -->"})
    with pytest.raises(bs.SiteError, match="no screenshot 'tray-menu'"):
        bs.build(tmp_path / "out", DEV, src, write_shots(tmp_path / "shots"))


def test_manifest_unreadable_or_empty(tmp_path: Path) -> None:
    shots = tmp_path / "shots"
    shots.mkdir()
    with pytest.raises(bs.SiteError, match="cannot read"):
        bs.load_screenshots(shots)
    (shots / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(bs.SiteError, match="no screenshots"):
        bs.load_screenshots(shots)


def test_manifest_entry_needs_alt_text(tmp_path: Path) -> None:
    shots = write_shots(tmp_path / "shots")
    data = json.loads((shots / "manifest.json").read_text(encoding="utf-8"))
    del data["main-window"]["alt"]
    (shots / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(bs.SiteError, match="has no 'alt'"):
        bs.load_screenshots(shots)


def test_manifest_missing_file(tmp_path: Path) -> None:
    shots = write_shots(tmp_path / "shots")
    (shots / "main-window.png").unlink()
    with pytest.raises(bs.SiteError, match="is missing"):
        bs.load_screenshots(shots)


def test_real_site_with_screenshots(tmp_path: Path) -> None:
    shots = tmp_path / "shots"
    manifest = {}
    shots.mkdir()
    for name in ("main-window", "close-prompt", "ftdi-error"):
        (shots / f"{name}.png").write_bytes(b"png")
        manifest[name] = {
            "file": f"{name}.png",
            "width": 10,
            "height": 10,
            "alt": name,
            "caption": name,
            **({"simulated": True} if name == "main-window" else {}),
        }
    (shots / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    pages = bs.build(tmp_path / "out", DEV, screenshots=shots)
    use = (tmp_path / "out" / "use.html").read_text(encoding="utf-8")
    assert use.count("<figure") == 3
    assert any(p.name == "use.html" for p in pages)
    assert bs.main(["--out", str(tmp_path / "m"), "--screenshots", str(shots)]) == 0


# --- screenshot groups (installer pages, #22) ----------------------------------------------


GROUP_PAGE = {"index.html": "<h1>x</h1><!-- screenshots:installer -->"}


def write_group(directory: Path, scenes: list[str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for scene in scenes:
        (directory / f"{scene}.png").write_bytes(b"png")
        manifest[scene] = {
            "file": f"{scene}.png",
            "width": 5,
            "height": 4,
            "alt": scene,
            "caption": scene,
            **({"simulated": True} if scene == "main-window" else {}),
        }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def test_group_renders_matching_scenes_in_capture_order(tmp_path: Path) -> None:
    shots = write_group(tmp_path / "s", ["main-window", "installer-license", "installer-tasks"])
    out = tmp_path / "out"
    bs.build(out, DEV, write_site(tmp_path / "src", GROUP_PAGE), shots)
    text = (out / "index.html").read_text(encoding="utf-8")
    assert '<div class="gallery">' in text
    assert text.index("shot-installer-license") < text.index("shot-installer-tasks")
    assert "shot-main-window" not in text
    assert bs.PREVIEW_LABEL in text


@pytest.mark.parametrize("with_shots", [True, False])
def test_group_without_matches_shows_the_note(tmp_path: Path, with_shots: bool) -> None:
    shots = write_group(tmp_path / "s", ["main-window"]) if with_shots else None
    out = tmp_path / "out"
    bs.build(out, RELEASE, write_site(tmp_path / "src", GROUP_PAGE), shots)
    text = (out / "index.html").read_text(encoding="utf-8")
    assert bs.GROUP_FALLBACK in text
    assert "<figure" not in text


def test_real_install_page_shows_installer_gallery(tmp_path: Path) -> None:
    shots = write_group(
        tmp_path / "s",
        ["main-window", "close-prompt", "ftdi-error", "installer-license", "installer-ftdi"],
    )
    bs.build(tmp_path / "out", DEV, screenshots=shots)
    install = (tmp_path / "out" / "install.html").read_text(encoding="utf-8")
    assert install.count("<figure") == 2


# --- user docs rendered into pages (#23) ------------------------------------------------------


def test_troubleshooting_page_lists_every_user_message(tmp_path: Path) -> None:
    import html as html_mod  # noqa: PLC0415 - local to keep the module's imports minimal

    from test_docs import USER_MESSAGES  # noqa: PLC0415

    bs.build(tmp_path / "out", DEV)
    page = (tmp_path / "out" / "troubleshooting.html").read_text(encoding="utf-8")
    assert "<table>" in page
    for message in USER_MESSAGES:
        assert html_mod.escape(message, quote=False) in page, message


def test_markdown_links_follow_the_release_ref(tmp_path: Path) -> None:
    bs.build(tmp_path / "out", RELEASE)
    page = (tmp_path / "out" / "troubleshooting.html").read_text(encoding="utf-8")
    assert f"/blob/{RELEASE['ref']}/docs/user/settings.md" in page


def test_markdown_marker_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = write_site(tmp_path / "src", {"index.html": "<!-- markdown:docs/user/nope.md -->"})
    with pytest.raises(bs.SiteError, match="does not exist"):
        bs.build(tmp_path / "out", DEV, src)
    root = tmp_path / "repo"
    (root / "docs" / "user").mkdir(parents=True)
    (root / "docs" / "user" / "bad.md").write_text("![x](y.png)", encoding="utf-8")
    monkeypatch.setattr(bs, "ROOT", root)
    src2 = write_site(tmp_path / "src2", {"index.html": "<!-- markdown:docs/user/bad.md -->"})
    with pytest.raises(bs.SiteError, match=r"bad\.md: unsupported"):
        bs.build(tmp_path / "out2", DEV, src2)
