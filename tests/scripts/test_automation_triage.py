# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import automation_triage as at
import pytest


def pr(number: int, ref: str, title: str = "t", body: str = "") -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "body": body,
        "head": {"ref": ref},
        "html_url": f"https://github.com/o/r/pull/{number}",
    }


def alert(number: int, desc: str = "Empty except") -> dict[str, Any]:
    return {
        "number": number,
        "rule": {"id": "py/x", "description": desc},
        "html_url": f"https://github.com/o/r/security/code-scanning/{number}",
    }


class FakeApi:
    """In-memory GitHub API covering the endpoints the script uses."""

    def __init__(
        self,
        prs: list[dict[str, Any]] | None = None,
        alerts: list[dict[str, Any]] | None = None,
        issues: list[dict[str, Any]] | None = None,
        label_exists: bool = True,
        alerts_status: int = 200,
    ) -> None:
        self.prs = prs or []
        self.alerts = alerts or []
        self.issues = issues or []
        self.label_exists = label_exists
        self.alerts_status = alerts_status
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, str]] = []

    def request(  # noqa: PLR0911, PLR0912 - one branch per fake endpoint
        self, method: str, path: str, body: Mapping[str, Any] | None = None
    ) -> Any:
        self.calls.append((method, path))
        if method == "GET" and path.startswith("/pulls"):
            return self.prs
        if method == "GET" and path.startswith("/code-scanning/alerts"):
            if self.alerts_status != 200:
                raise at.ApiError(self.alerts_status, "no access")
            return self.alerts
        if method == "GET" and path.startswith(f"/labels/{at.LABEL}"):
            if not self.label_exists:
                raise at.ApiError(404, "Not Found")
            return {"name": at.LABEL}
        if method == "POST" and path == "/labels":
            self.label_exists = True
            return body
        if path.endswith("/labels") and method == "POST":
            return []
        if method == "DELETE" and f"/labels/{at.LABEL}" in path:
            return None
        if path.endswith("/comments") or "/comments?" in path:
            number = int(path.split("/")[2])
            if method == "GET":
                return self.comments.get(number, [])
            self.comments.setdefault(number, []).append(dict(body or {}))
            return body
        if method == "GET" and path.startswith("/issues?"):
            return self.issues
        if method == "POST" and path == "/issues":
            issue = {"number": 900 + len(self.issues), "state": "open", **dict(body or {})}
            self.issues.append(issue)
            return issue
        if method == "PATCH" and path.startswith("/issues/"):
            number = int(path.split("/")[2])
            issue = next(i for i in self.issues if i["number"] == number)
            issue.update(body or {})
            return issue
        raise AssertionError(f"unexpected call {method} {path}")  # pragma: no cover

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] != "GET"]


# --- detection ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("alert-autofix-21", True),
        ("dependabot/uv/ruff-0.7", True),
        ("issue-30-udp", False),
        ("autofix", False),
    ],
)
def test_is_automated(ref: str, expected: bool) -> None:
    assert at.is_automated(pr(1, ref)) is expected


def test_referenced_alerts() -> None:
    prs = [
        pr(1, "x", body="Fixes https://github.com/o/r/security/code-scanning/5"),
        pr(2, "y", title="Potential fix for code scanning alert no. 21: Empty except"),
        pr(3, "z", body=None),  # type: ignore[arg-type]
    ]
    assert at.referenced_alerts(prs) == {5, 21}


def test_find_pending_lists_automated_prs_and_uncovered_alerts() -> None:
    api = FakeApi(
        prs=[
            pr(65, "alert-autofix-5", body="code-scanning/5"),
            pr(70, "issue-70-readme"),
            pr(80, "dependabot/github_actions/x"),
        ],
        alerts=[alert(5), alert(9, "Unused import")],
    )
    pending = at.find_pending(api)
    assert [(p.kind, p.number) for p in pending] == [("pr", 65), ("pr", 80), ("alert", 9)]
    assert pending[2].title == "Unused import"


def test_alert_listing_failure_is_a_warning() -> None:
    warnings: list[str] = []
    api = FakeApi(prs=[pr(80, "dependabot/x")], alerts_status=403)
    pending = at.find_pending(api, warn=warnings.append)
    assert [p.number for p in pending] == [80]
    assert "could not list code-scanning alerts" in warnings[0]


def test_alert_title_falls_back_to_rule_id() -> None:
    api = FakeApi(alerts=[{"number": 3, "rule": {"id": "py/foo"}, "html_url": "u"}])
    assert at.find_pending(api)[0].title == "py/foo"


# --- flagging PRs -----------------------------------------------------------------------


def test_run_labels_and_comments_once() -> None:
    api = FakeApi(prs=[pr(65, "alert-autofix-5")], label_exists=False)
    out: list[str] = []
    assert at.run(api, out=out.append) == 0
    assert at.run(api, out=out.append) == 0
    assert ("POST", "/labels") in api.calls
    assert len(api.comments[65]) == 1  # idempotent
    assert at.MARKER in api.comments[65][0]["body"]
    assert ("POST", "/issues/65/labels") in api.calls


def test_ensure_label_propagates_other_errors() -> None:
    class Broken(FakeApi):
        def request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
            if path.startswith("/labels/"):
                raise at.ApiError(500, "boom")
            return super().request(method, path, body)

    with pytest.raises(at.ApiError, match="500"):
        at.ensure_label(Broken())


def test_never_touches_branches_checks_or_merges() -> None:
    api = FakeApi(prs=[pr(65, "alert-autofix-5")], alerts=[alert(9)])
    at.run(api, out=lambda _: None)
    for _method, path in api.writes():
        assert not path.startswith(("/git/", "/contents/", "/actions/", "/merges"))
        assert "/merge" not in path
        assert not path.startswith("/pulls/")  # PR bodies are never edited


# --- triage issue ------------------------------------------------------------------------


def test_render_body() -> None:
    body = at.render_body(
        [at.Pending("pr", 65, "Fix", "u1"), at.Pending("alert", 9, "Unused import", "u2")]
    )
    assert "- [ ] PR #65: [Fix](u1)" in body
    assert "- [ ] Code-scanning alert #9: [Unused import](u2)" in body
    assert "Nothing is waiting" in at.render_body([])


def test_no_issue_created_when_nothing_pending() -> None:
    api = FakeApi()
    out: list[str] = []
    at.run(api, out=out.append)
    assert out[-1] == "no triage issue needed"
    assert api.writes() == []


def test_issue_created_then_closed_then_reopened() -> None:
    api = FakeApi(prs=[pr(65, "alert-autofix-5")])
    assert at.update_triage_issue(api, at.find_pending(api)).startswith("created triage issue")
    issue = api.issues[0]
    assert issue["labels"] == [at.TRIAGE_LABEL]
    assert issue["title"] == at.TRIAGE_TITLE

    api.prs = []
    assert at.update_triage_issue(api, []).endswith("(closed)")
    assert issue["state"] == "closed"
    assert at.update_triage_issue(api, []).endswith("unchanged (closed)")

    api.prs = [pr(80, "dependabot/x")]
    assert at.update_triage_issue(api, at.find_pending(api)).endswith("(open)")
    assert issue["state"] == "open"
    assert "PR #80" in issue["body"]


def test_triage_issue_ignores_pull_requests_and_other_titles() -> None:
    api = FakeApi(
        issues=[
            {"number": 1, "title": at.TRIAGE_TITLE, "pull_request": {}, "state": "open"},
            {"number": 2, "title": "Other", "state": "open"},
        ]
    )
    assert at.find_triage_issue(api) is None


def test_dry_run_changes_nothing() -> None:
    api = FakeApi(prs=[pr(65, "alert-autofix-5")], alerts=[alert(9)])
    out: list[str] = []
    assert at.run(api, dry_run=True, out=out.append) == 0
    assert api.writes() == []
    assert out[0] == "2 item(s) waiting for adoption"
    assert any("PR #65" in line for line in out)


# --- adopted automated PRs (#83) ---------------------------------------------------


def test_adopted_autofix_pr_is_not_pending_and_is_unflagged() -> None:
    adopted = pr(65, "alert-autofix-21", body="Closes #90\n\nPotential fix")
    adopted["labels"] = [{"name": at.LABEL}]
    fresh = pr(66, "alert-autofix-22", body="Potential fix")
    api = FakeApi(prs=[adopted, fresh])
    assert [p.number for p in at.find_pending(api)] == [66]
    out: list[str] = []
    at.run(api, out=out.append)
    assert ("DELETE", f"/issues/65/labels/{at.LABEL}") in api.calls
    assert any("PR #65 adopted" in line for line in out)


def test_is_adopted_and_has_label() -> None:
    assert at.is_adopted(pr(1, "x", body="fixes #4"))
    assert not at.is_adopted(pr(1, "x", body="see #4"))
    assert at.has_label({"labels": [at.LABEL]})
    assert not at.has_label({"labels": [{"name": "other"}]})
