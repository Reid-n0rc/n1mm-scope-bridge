# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Fails CI when a user-facing feature is undocumented (issue #31)."""

from __future__ import annotations

import argparse
import dataclasses
import re
from pathlib import Path

import pytest

from n1mm_scope_bridge.cli import build_parser
from n1mm_scope_bridge.radios import RADIOS
from n1mm_scope_bridge.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
USER = ROOT / "docs" / "user"
SRC = ROOT / "src" / "n1mm_scope_bridge"

# Every message a user can see. Each must exist in the source (so this list
# can't go stale) and in troubleshooting.md (so users can look it up).
USER_MESSAGES = [
    "The window needs PySide6",
    "Could not load FTDI's LibFT4222/D2XX libraries",
    "has no working FTDI USB",
    "FTDI library folder does not exist",
    "Found FTDI DLLs built for",
    "FTDI library is missing a required function",
    "Could not open",
    "No valid scope frames from",
    "frequency edges are only exact in Center mode",
    "unknown radio",
    "was recorded from a",
    "not an n1mm-scope-bridge capture",
    "trailing partial frame",
    "not an n1mm-scope-bridge raw stream capture",
    "raw chunk of",
    "truncated raw",
    "capture has no frames to loop",
    "unsupported capture format",
    "capture model name",
    "frame size must be in",
    "capture frame is",
    "replay fps must be >= 0",
    "--frames must be at least 1",
    "--name must not be empty",
    "port must be 1-65535",
    "Could not start remote control on",
    "No reply from n1mm-scope-bridge at",
    "control port must",
    "control address must",
    "a non-loopback control address needs",
]
USER_ERROR_RAISE = re.compile(
    r"raise (?:UserError|LibraryNotFound|DeviceNotFound|CaptureError)\(\s*f?\"([^\"{]{6,})"
)


def read(name: str) -> str:
    return (USER / name).read_text(encoding="utf-8")


def commands() -> dict[str, argparse.ArgumentParser]:
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise AssertionError("no subcommands")  # pragma: no cover


def documented_options(parser: argparse.ArgumentParser) -> list[str]:
    opts = [o for a in parser._actions for o in a.option_strings if o not in ("-h", "--help")]
    positional = [a.dest.upper() for a in parser._actions if not a.option_strings]
    return opts + positional


def command_page(name: str) -> str:
    return (USER / "cli" / f"{name}.md").read_text(encoding="utf-8")


def test_every_command_has_its_own_page() -> None:
    pages = {p.stem for p in (USER / "cli").glob("*.md")}
    assert pages == set(commands()), "docs/user/cli/ must have exactly one page per command"


@pytest.mark.parametrize("command", sorted(commands()))
def test_every_option_is_documented(command: str) -> None:
    doc = command_page(command)
    assert doc.startswith(f"# `{command}`"), f"cli/{command}.md must start with its heading"
    for option in documented_options(commands()[command]):
        assert f"`{option}" in doc, f"cli/{command}.md does not document {option}"


def test_global_options_documented() -> None:
    doc = read("cli.md")
    for option in ("--version", "--license", "--help"):
        assert option in doc


def test_every_setting_is_documented() -> None:
    doc = read("settings.md")
    for field in dataclasses.fields(Settings):
        assert f"| `{field.name}` |" in doc, f"settings.md does not document {field.name}"


def test_settings_defaults_in_docs_match_code() -> None:
    doc = read("settings.md")
    defaults = Settings()
    for name in ("radio", "n1mm_host", "n1mm_port", "combine", "device", "on_close"):
        assert f"| `{name}` | `{getattr(defaults, name)}` |" in doc, name


@pytest.mark.parametrize("message", USER_MESSAGES)
def test_user_message_exists_and_is_documented(message: str) -> None:
    source = "".join(p.read_text(encoding="utf-8") for p in SRC.rglob("*.py"))
    assert message in source, f"stale USER_MESSAGES entry: {message!r}"
    assert message in read("troubleshooting.md"), f"troubleshooting.md lacks {message!r}"


def test_every_user_error_raise_is_listed() -> None:
    """New `raise UserError("...")` style messages must be added to USER_MESSAGES."""
    for path in SRC.rglob("*.py"):
        for literal in USER_ERROR_RAISE.findall(path.read_text(encoding="utf-8")):
            assert any(m in literal or literal in m for m in USER_MESSAGES), (
                f"{path.name}: undocumented user-facing error {literal!r}"
            )


def test_doc_links_resolve() -> None:
    for page in USER.rglob("*.md"):
        for target in re.findall(r"\]\(([^)#:]+\.md)\)", page.read_text(encoding="utf-8")):
            assert (page.parent / target).resolve().exists(), f"{page.name} -> {target}"


def test_checker_catches_an_undocumented_option() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand-new-option")
    missing = [o for o in documented_options(parser) if f"`{o}" not in command_page("run")]
    assert missing == ["--brand-new-option"]


def test_radio_setup_page_documents_scu_lan10() -> None:
    """The FT-710 scope output depends on a radio menu setting; keep it documented."""
    page = read("radios/ft-710.md")
    assert "OPERATION SETTING → GENERAL → SCU-LAN10" in page
    assert "EX 03-01-26" in page
    assert "**ON**" in page
    assert "radios/README.md" in read("radio-setup.md")
    for linked in (ROOT / "README.md", ROOT / "docs" / "n1mm-setup.md"):
        assert "radio-setup.md" in linked.read_text(encoding="utf-8"), linked.name


# Every radio setup page has these sections, in this order (#194).
RADIO_PAGE_HEADINGS = (
    "## What you need",
    "## Required settings",
    "## Make the PC see the scope",
    "## Check it works",
    "## Undo",
)
# Each setting under "## Required settings" (one "### " heading per setting) says
# where it is and how to get there.
RADIO_SETTING_FIELDS = ("**Menu path:**", "**Menu number:**", "**Button presses:**")


def radio_slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _setting_problems(model: str, text: str) -> list[str]:
    settings = text.split("\n## Required settings\n", 1)[1].split("\n## ", 1)[0]
    blocks = settings.split("\n### ")[1:]
    if not blocks:
        return [f"{model}: Required settings has no '### <setting>'"]
    return [
        f"{model}: {block.splitlines()[0]}: missing {field}"
        for block in blocks
        for field in RADIO_SETTING_FIELDS
        if field not in block
    ]


def radio_page_problems(user: Path, site: Path, models: list[str]) -> list[str]:
    """What is missing for each supported radio's setup page and site page."""
    problems = []
    index_text = _text(user / "radios" / "README.md")
    if not index_text:
        problems.append("docs/user/radios/README.md is missing")
    picker_text = _text(site / "radios.html")
    if "<!-- markdown:docs/user/radios/README.md -->" not in picker_text:
        problems.append("site/radios.html must render docs/user/radios/README.md")
    for model in models:
        slug = radio_slug(model)
        text = _text(user / "radios" / f"{slug}.md")
        if not text:
            problems.append(f"{model}: docs/user/radios/{slug}.md is missing")
            continue
        lines = text.splitlines()
        found = [line for line in lines if line in RADIO_PAGE_HEADINGS]
        if found != list(RADIO_PAGE_HEADINGS):
            problems.append(f"{model}: needs the sections {', '.join(RADIO_PAGE_HEADINGS)}")
        else:
            problems += _setting_problems(model, text)
        if f"({slug}.md)" not in index_text:
            problems.append(f"{model}: docs/user/radios/README.md must link {slug}.md")
        marker = f"<!-- markdown:docs/user/radios/{slug}.md -->"
        if marker not in _text(site / f"radio-{slug}.html"):
            problems.append(f"{model}: site/radio-{slug}.html must render {slug}.md")
        if f'href="radio-{slug}.html"' not in picker_text:
            problems.append(f"{model}: site/radios.html must link radio-{slug}.html")
    return problems


def test_every_supported_radio_has_a_setup_page() -> None:
    models = [profile.model for profile in RADIOS.values()]
    assert radio_page_problems(USER, ROOT / "site", models) == []


GOOD_RADIO_PAGE = """# Radio X

## What you need

USB.

## Required settings

### Scope: ON

- **Menu path:** A → B
- **Menu number:** 1

**Button presses:**

1. Press it.

## Make the PC see the scope

Replug.

## Check it works

Start.

## Undo

OFF.
"""


def write_radio_docs(tmp_path: Path, page: str | None = GOOD_RADIO_PAGE) -> tuple[Path, Path]:
    user, site = tmp_path / "user", tmp_path / "site"
    (user / "radios").mkdir(parents=True)
    site.mkdir()
    (user / "radios" / "README.md").write_text("[X](radio-x.md)\n", encoding="utf-8")
    if page is not None:
        (user / "radios" / "radio-x.md").write_text(page, encoding="utf-8")
    (site / "radios.html").write_text(
        '<!-- markdown:docs/user/radios/README.md --><a href="radio-radio-x.html">X</a>',
        encoding="utf-8",
    )
    (site / "radio-radio-x.html").write_text(
        "<!-- markdown:docs/user/radios/radio-x.md -->", encoding="utf-8"
    )
    return user, site


def test_radio_page_checker_accepts_a_complete_page(tmp_path: Path) -> None:
    assert radio_page_problems(*write_radio_docs(tmp_path), ["Radio X"]) == []


def test_radio_page_checker_catches_a_missing_page(tmp_path: Path) -> None:
    problems = radio_page_problems(*write_radio_docs(tmp_path, None), ["Radio X"])
    assert problems == ["Radio X: docs/user/radios/radio-x.md is missing"]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (("## Undo\n", "## Revert\n"), "needs the sections"),
        (("**Button presses:**", "Steps:"), "Scope: ON: missing **Button presses:**"),
        (("### Scope: ON", "Scope: ON"), "has no '### <setting>'"),
    ],
)
def test_radio_page_checker_catches_an_incomplete_page(
    tmp_path: Path, change: tuple[str, str], expected: str
) -> None:
    page = GOOD_RADIO_PAGE.replace(*change)
    problems = radio_page_problems(*write_radio_docs(tmp_path, page), ["Radio X"])
    assert len(problems) == 1
    assert expected in problems[0]


def test_radio_page_checker_catches_sections_out_of_order(tmp_path: Path) -> None:
    page = GOOD_RADIO_PAGE.replace("## Undo\n\nOFF.\n", "").replace(
        "## What you need", "## Undo\n\nOFF.\n\n## What you need"
    )
    problems = radio_page_problems(*write_radio_docs(tmp_path, page), ["Radio X"])
    assert problems == ["Radio X: needs the sections " + ", ".join(RADIO_PAGE_HEADINGS)]


def test_radio_page_checker_catches_missing_index_and_site_links(tmp_path: Path) -> None:
    user, site = write_radio_docs(tmp_path)
    (user / "radios" / "README.md").write_text("nothing\n", encoding="utf-8")
    (site / "radios.html").write_text("", encoding="utf-8")
    (site / "radio-radio-x.html").unlink()
    assert radio_page_problems(user, site, ["Radio X"]) == [
        "site/radios.html must render docs/user/radios/README.md",
        "Radio X: docs/user/radios/README.md must link radio-x.md",
        "Radio X: site/radio-radio-x.html must render radio-x.md",
        "Radio X: site/radios.html must link radio-radio-x.html",
    ]
    (user / "radios" / "README.md").unlink()
    assert "docs/user/radios/README.md is missing" in radio_page_problems(user, site, [])


def test_code_signing_policy_and_privacy_pages() -> None:
    """SignPath Foundation requires a public code signing policy and privacy statement."""
    policy = (ROOT / "docs" / "code-signing-policy.md").read_text(encoding="utf-8")
    assert "Free code signing provided by SignPath.io, certificate by SignPath Foundation" in policy
    for role in ("Authors", "Reviewers", "Approvers"):
        assert role in policy
    assert "multi-factor authentication" in policy
    privacy = (ROOT / "docs" / "privacy.md").read_text(encoding="utf-8")
    assert "no personal data" in privacy
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/code-signing-policy.md" in readme
    assert "docs/privacy.md" in readme
    footer = (ROOT / "site" / "_partials" / "footer.html").read_text(encoding="utf-8")
    assert "code-signing.html" in footer
    assert "privacy.html" in footer
    site_policy = (ROOT / "site" / "code-signing.html").read_text(encoding="utf-8")
    assert "Free code signing provided by" in site_policy


def test_privacy_notice_covers_gdpr_topics() -> None:
    """GDPR-style privacy notice (issue #142)."""
    privacy = (ROOT / "docs" / "privacy.md").read_text(encoding="utf-8")
    for topic in (
        "Last updated:",
        "## Who is responsible",
        "## Third parties",
        "## Your rights",
        "## Children",
        "## Changes",
        "no cookies",
        "PyPI",
        "GitHub Pages",
        "Copy diagnostics",
    ):
        assert topic in privacy, topic
    site_page = (ROOT / "site" / "privacy.html").read_text(encoding="utf-8")
    assert "Last updated: " + privacy.split("Last updated: ", 1)[1].split("_", 1)[0] in site_page


def test_issue_templates_warn_about_personal_data() -> None:
    for name in ("bug_report.yml", "feature_request.yml", "radio_support.yml"):
        text = (ROOT / ".github" / "ISSUE_TEMPLATE" / name).read_text(encoding="utf-8")
        assert "Issues are public" in text, name
