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
from n1mm_scope_bridge.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
USER = ROOT / "docs" / "user"
SRC = ROOT / "src" / "n1mm_scope_bridge"

# Every message a user can see. Each must exist in the source (so this list
# can't go stale) and in troubleshooting.md (so users can look it up).
USER_MESSAGES = [
    "The window needs PySide6",
    "Could not load FTDI's LibFT4222/D2XX libraries",
    "FTDI library folder does not exist",
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
