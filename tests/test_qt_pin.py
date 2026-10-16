# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The PySide6 bound stays the same in the gui extra and the gui-dev group.

The <6.12 stop-gap (#236) was lifted once the freeze was fixed at the source
(#238), so neither carries an upper bound and the lock is on 6.12 or later.

Plain text checks, so they also run on Python 3.10 (no ``tomllib``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIN = '"PySide6-Essentials>=6.8"'


def _lines(name: str) -> list[str]:
    return (ROOT / name).read_text(encoding="utf-8").splitlines()


def _locked_versions(lock: str, package: str) -> list[str]:
    """Every ``version`` recorded for ``package`` in uv.lock text."""
    return re.findall(rf'^name = "{re.escape(package)}"\nversion = "([^"]+)"', lock, re.MULTILINE)


def _major_minor(version: str) -> tuple[int, int]:
    major, minor = version.split(".")[:2]
    return int(major), int(minor)


@pytest.mark.parametrize("key", ["gui = [", "gui-dev = ["])
def test_gui_extra_and_dev_group_share_the_pin(key: str) -> None:
    lines = [line for line in _lines("pyproject.toml") if line.startswith(key)]
    assert len(lines) == 1, lines
    assert PIN in lines[0]


@pytest.mark.parametrize("package", ["pyside6-essentials", "shiboken6"])
def test_lock_resolves_qt_6_12_or_later(package: str) -> None:
    versions = _locked_versions((ROOT / "uv.lock").read_text(encoding="utf-8"), package)
    assert versions, f"{package} missing from uv.lock"
    assert all(_major_minor(v) >= (6, 12) for v in versions), versions


def test_locked_versions_parses_entries() -> None:
    lock = 'name = "shiboken6"\nversion = "6.11.2"\n\nname = "other"\nversion = "1.0"\n'
    assert _locked_versions(lock, "shiboken6") == ["6.11.2"]
    assert _locked_versions(lock, "pyside6-essentials") == []


def test_major_minor() -> None:
    assert _major_minor("6.11.2") == (6, 11)
    assert _major_minor("6.12") == (6, 12)
