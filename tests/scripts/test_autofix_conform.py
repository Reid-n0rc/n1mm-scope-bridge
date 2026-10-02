# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import autofix_conform as ac
import pytest

REPO = "Reid-n0rc/n1mm-scope-bridge"
BODY = "Potential fix for [alert](https://github.com/Reid-n0rc/n1mm-scope-bridge/security/code-scanning/21)"
ALERT = {"rule": {"id": "py/empty-except", "description": "Empty except"},
         "most_recent_instance": {"location": {"path": "src/x.py"}}}  # fmt: skip


class FakeGh:
    def __init__(self, pr: dict[str, Any] | None = None, **over: Any) -> None:
        self.pr = {
            "number": 65, "title": "Potential fix", "body": BODY,
            "headRefName": "alert-autofix-21", "baseRefName": "dev",
            "isCrossRepository": False, "labels": [{"name": "needs-adoption"}], "state": "OPEN",
            **(pr or {}),
        }  # fmt: skip
        self.issues: list[dict[str, Any]] = over.get("issues", [])
        self.fragment_exists = over.get("fragment_exists", False)
        self.alert_ok = over.get("alert_ok", True)
        self.fail: str | None = over.get("fail")
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: Sequence[str]) -> tuple[int, str]:  # noqa: PLR0911 - fake router
        a = tuple(args)
        self.calls.append(a)
        if self.fail and self.fail in " ".join(a):
            return 1, "boom"
        if a[:2] == ("pr", "view"):
            return 0, json.dumps(self.pr)
        if a[0] == "api" and "code-scanning/alerts" in a[1]:
            return (0, json.dumps(ALERT)) if self.alert_ok else (1, "404")
        if a[:2] == ("issue", "list"):
            return 0, json.dumps(self.issues)
        if a[:2] == ("issue", "create"):
            return 0, "https://github.com/Reid-n0rc/n1mm-scope-bridge/issues/90\n"
        if a[0] == "api" and "contents/" in a[1] and "-X" not in a:
            return (0, "{}") if self.fragment_exists else (1, "Not Found")
        return 0, ""

    def find(self, *prefix: str) -> list[tuple[str, ...]]:
        return [c for c in self.calls if c[: len(prefix)] == prefix]


def conform(gh: FakeGh) -> ac.Result:
    return ac.Conformer(REPO, gh).conform(65)


def test_full_conformance_of_new_autofix_pr() -> None:
    gh = FakeGh(pr={"baseRefName": "main"})
    result = conform(gh)
    assert result.issue == 90
    create = gh.find("issue", "create")[0]
    assert "Code scanning alert #21: Empty except (src/x.py)" in create
    assert create[create.index("--assignee") :][:2] == ("--assignee", "Reid-n0rc")
    for label in ac.ISSUE_LABELS:
        assert label in create
    edits = gh.find("pr", "edit")
    assert any("--base" in e and "dev" in e for e in edits)
    body_edit = next(e for e in edits if "--body" in e)
    assert body_edit[body_edit.index("--body") + 1].startswith("Closes #90\n")
    put = next(c for c in gh.calls if c[:3] == ("api", "-X", "PUT"))
    assert put[3].endswith("contents/changelog.d/90.security.md")
    assert "branch=alert-autofix-21" in put
    assert any("--remove-label" in e for e in edits)
    runs = gh.find("workflow", "run")
    assert [r[2] for r in runs] == ["ci.yml", "codeql.yml", "changelog.yml", "issue-policy.yml"]
    assert all(r[r.index("--ref") + 1] == "alert-autofix-21" for r in runs)
    assert runs[3][-2:] == ("-f", "pr=65")
    comment = gh.find("pr", "comment")[0]
    assert ac.MARKER in comment[-1]
    assert "#90" in comment[-1]


def test_idempotent_when_already_conformed() -> None:
    gh = FakeGh(
        pr={"body": "Closes #90\n\n" + BODY, "labels": []},
        issues=[{"number": 90, "title": "Code scanning alert #21: Empty except", "state": "OPEN"}],
        fragment_exists=True,
    )
    result = conform(gh)
    assert result.issue == 90
    assert not gh.find("issue", "create")
    assert not [e for e in gh.find("pr", "edit") if "--body" in e or "--base" in e]
    assert not [c for c in gh.calls if c[:3] == ("api", "-X", "PUT")]
    assert "reused tracking issue #90" in result.actions


def test_alert_lookup_failure_uses_generic_rule() -> None:
    gh = FakeGh(alert_ok=False)
    conform(gh)
    assert "Code scanning alert #21: code scanning alert" in gh.find("issue", "create")[0]


@pytest.mark.parametrize(
    ("pr", "message"),
    [
        ({"headRefName": "issue-5-thing"}, "not a Copilot Autofix PR"),
        ({"isCrossRepository": True}, "fork"),
        ({"state": "CLOSED"}, "not open"),
        ({"body": "no alert link here"}, "does not link"),
    ],
)
def test_guards(pr: dict[str, Any], message: str) -> None:
    gh = FakeGh(pr=pr)
    with pytest.raises(ac.ConformError, match=message):
        conform(gh)
    assert not gh.find("issue", "create")
    assert not gh.find("workflow", "run")


def test_gh_failure_is_reported() -> None:
    with pytest.raises(ac.ConformError, match="failed"):
        conform(FakeGh(fail="issue create"))


def test_main_usage_and_outcomes(capsys: pytest.CaptureFixture[str]) -> None:
    assert ac.main([]) == 2
    assert ac.main(["65"], gh=FakeGh()) == 0
    assert "PR #65 conformed" in capsys.readouterr().out
    assert ac.main(["65"], gh=FakeGh(pr={"isCrossRepository": True})) == 0
    assert "Not conformed" in capsys.readouterr().out
