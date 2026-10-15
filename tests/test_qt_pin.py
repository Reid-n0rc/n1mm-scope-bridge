# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""PySide6 stays below 6.12 until the Windows GUI freeze is fixed (#236).

Plain text checks, so they also run on Python 3.10 (no ``tomllib``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIN = '"PySide6-Essentials>=6.8,<6.12"'


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
def test_lock_resolves_qt_below_6_12(package: str) -> None:
    versions = _locked_versions((ROOT / "uv.lock").read_text(encoding="utf-8"), package)
    assert versions, f"{package} missing from uv.lock"
    assert all((6, 8) <= _major_minor(v) < (6, 12) for v in versions), versions


def test_locked_versions_parses_entries() -> None:
    lock = 'name = "shiboken6"\nversion = "6.11.2"\n\nname = "other"\nversion = "1.0"\n'
    assert _locked_versions(lock, "shiboken6") == ["6.11.2"]
    assert _locked_versions(lock, "pyside6-essentials") == []


def test_major_minor() -> None:
    assert _major_minor("6.11.2") == (6, 11)
    assert _major_minor("6.12") == (6, 12)
