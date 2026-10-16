# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Text the app shows stays inside the UI font, so Qt never needs font fallback (#238).

A character that Segoe UI lacks, such as U+2713 (check mark) or U+26A0
(warning sign), makes Qt ask DirectWrite for fallback families. On Qt 6.12
that creates a font face for every candidate family. On a freshly started
Windows PC this read font files from a cold disk for 10 to 45 s, on the GUI
thread with the GIL held, and every pipeline thread stopped with it.

The guard covers every source file in the package, because log, status and
About text from outside ``gui/`` is shown in the window too. Plain text
checks, no Qt needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "n1mm_scope_bridge"

# Beyond Latin-1: characters in WGL4, which Segoe UI (the Windows UI font) covers.
ALLOWED = frozenset("\u2013\u2014\u2018\u2019\u201c\u201d\u2026\u2192")


def font_safe(char: str) -> bool:
    """True if Segoe UI draws ``char`` itself, without system font fallback."""
    return ord(char) <= 0xFF or char in ALLOWED


def unsafe_chars(text: str) -> list[tuple[int, str]]:
    """``(line number, character)`` for each character that would need fallback."""
    return [
        (number, char)
        for number, line in enumerate(text.splitlines(), start=1)
        for char in line
        if not font_safe(char)
    ]


@pytest.mark.parametrize(
    "path", sorted(PACKAGE.rglob("*.py")), ids=lambda p: p.relative_to(PACKAGE).as_posix()
)
def test_source_text_needs_no_font_fallback(path: Path) -> None:
    found = unsafe_chars(path.read_text(encoding="utf-8"))
    assert not found, [f"line {n}: U+{ord(c):04X} {c!r}" for n, c in found]


def test_package_has_source_files() -> None:
    assert len(list(PACKAGE.rglob("*.py"))) > 10


@pytest.mark.parametrize("char", ["a", "~", "\u00b7", "\u00e9", "\u00ff", *sorted(ALLOWED)])
def test_font_safe_accepts_latin1_and_wgl4_punctuation(char: str) -> None:
    assert font_safe(char)


@pytest.mark.parametrize("char", ["\u2713", "\u26a0", "\u2714", "\u0100", "\u4e2d", "\U0001f600"])
def test_font_safe_rejects_characters_that_need_fallback(char: str) -> None:
    assert not font_safe(char)


def test_unsafe_chars_reports_line_and_character() -> None:
    text = "ok \u2014 fine\n\u2713 Exact frequencies\n\n\u26a0 port"
    assert unsafe_chars(text) == [(2, "\u2713"), (4, "\u26a0")]
    assert unsafe_chars("") == []
    assert unsafe_chars("Settings \u2192 Radio \u2026") == []
