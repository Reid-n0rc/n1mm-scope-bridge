# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The flaky GUI test quarantine in conftest.py (#222)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytest_plugins = ("pytester",)

CONFTEST = Path(__file__).with_name("conftest.py")
ISSUE = "https://github.com/Reid-n0rc/n1mm-scope-bridge/issues/222"

# Fails on the first attempt only; the counter file lives in pytester's tmp dir.
FLAKY_BODY = """
import pathlib
import pytest

{marks}
def test_sometimes():
    seen = pathlib.Path(__file__).with_name("attempts")
    count = int(seen.read_text()) + 1 if seen.exists() else 1
    seen.write_text(str(count))
    assert count > 1
"""


@pytest.fixture
def quarantine(pytester: pytest.Pytester) -> pytest.Pytester:
    """A pytester dir that runs this repository's conftest.py."""
    pytester.makeconftest(CONFTEST.read_text(encoding="utf-8"))
    pytester.makeini(
        "[pytest]\n"
        "markers =\n    gui: needs PySide6\n"
        "addopts = --strict-markers -p no:cacheprovider\n"
    )
    return pytester


def write_test(pytester: pytest.Pytester, *marks: str) -> None:
    pytester.makepyfile(test_sometimes=FLAKY_BODY.format(marks="\n".join(marks)))


def test_marked_gui_test_reruns_once_and_is_reported(quarantine: pytest.Pytester) -> None:
    write_test(quarantine, "@pytest.mark.gui", f'@pytest.mark.flaky(reruns=1, reason="{ISSUE}")')
    result = quarantine.runpytest("-rR", "--junitxml=junit.xml", "-o", "junit_family=legacy")
    assert result.parseoutcomes() == {"passed": 1, "rerun": 1}
    result.stdout.fnmatch_lines(["RERUN test_sometimes.py::test_sometimes"])
    cases = ET.parse(quarantine.path / "junit.xml").getroot().iter("testcase")
    props = [p.attrib for case in cases for p in case.iter("property")]
    assert props == [{"name": "flaky_rerun", "value": "1"}]


def test_one_rerun_is_all_a_quarantined_test_gets(quarantine: pytest.Pytester) -> None:
    quarantine.makepyfile(
        test_always=f"""
import pytest

@pytest.mark.gui
@pytest.mark.flaky(reruns=1, reason="{ISSUE}")
def test_always():
    assert False
"""
    )
    result = quarantine.runpytest()
    assert result.parseoutcomes() == {"failed": 1, "rerun": 1}


def test_unmarked_test_never_reruns(quarantine: pytest.Pytester) -> None:
    write_test(quarantine, "@pytest.mark.gui")
    result = quarantine.runpytest()
    result.assert_outcomes(failed=1)


@pytest.mark.parametrize(
    ("marks", "message"),
    [
        (
            [f'@pytest.mark.flaky(reruns=1, reason="{ISSUE}")'],
            "*flaky quarantine is for gui tests only*",
        ),
        (
            ["@pytest.mark.gui", f'@pytest.mark.flaky(reruns=2, reason="{ISSUE}")'],
            "*allows exactly one rerun, not 2*",
        ),
        (
            ["@pytest.mark.gui", f'@pytest.mark.flaky(reruns=True, reason="{ISSUE}")'],
            "*allows exactly one rerun, not True*",
        ),
        (
            ["@pytest.mark.gui", "@pytest.mark.flaky(reruns=1)"],
            "*use @pytest.mark.flaky(reruns=1, reason=<GitHub issue URL>)*",
        ),
        (
            ["@pytest.mark.gui", f'@pytest.mark.flaky(1, reason="{ISSUE}")'],
            "*use @pytest.mark.flaky(reruns=1, reason=<GitHub issue URL>)*",
        ),
        (
            ["@pytest.mark.gui", f'@pytest.mark.flaky(reruns=1, reason="{ISSUE}", reruns_delay=5)'],
            "*use @pytest.mark.flaky(reruns=1, reason=<GitHub issue URL>)*",
        ),
        (
            ["@pytest.mark.gui", '@pytest.mark.flaky(reruns=1, reason="flaky on Windows")'],
            "*reason must link the tracking issue*",
        ),
    ],
)
def test_bad_quarantine_is_a_usage_error(
    quarantine: pytest.Pytester, marks: list[str], message: str
) -> None:
    write_test(quarantine, *marks)
    result = quarantine.runpytest()
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines([message])


@pytest.mark.parametrize("option", ["--reruns=1", "--force-reruns=1"])
def test_suite_wide_reruns_are_a_usage_error(quarantine: pytest.Pytester, option: str) -> None:
    write_test(quarantine, "@pytest.mark.gui")
    result = quarantine.runpytest(option)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines([f"*{option.partition('=')[0]} is not allowed*"])
