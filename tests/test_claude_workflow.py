# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Guard the Claude Code Action pilot's trigger gate and permissions (#224).

The workflow is checked as text (the runtime has no YAML parser), which is
enough for the few lines that make up the gate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "claude.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")


def _job_if() -> str:
    match = re.search(r"^    if: >-\n(.*?)^    runs-on:", TEXT, re.MULTILINE | re.DOTALL)
    assert match, "claude.yml job has no folded `if: >-` block"
    return match.group(1)


def _branches() -> dict[str, str]:
    """The `if:` split into its three `(github.event_name == '...' ...)` branches."""
    gate = _job_if()
    starts = [
        (m.start(), m.group(1)) for m in re.finditer(r"github\.event_name == '([a-z_]+)'", gate)
    ]
    ends = [s for s, _ in starts[1:]] + [len(gate)]
    return {name: gate[start:end] for (start, name), end in zip(starts, ends, strict=True)}


def test_triggers_are_created_or_labeled_only_and_never_pull_request_target() -> None:
    on = TEXT.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "pull_request_target" not in on
    assert "workflow_run" not in on
    assert re.findall(r"^  ([a-z_]+):", on, re.MULTILINE) == [
        "issues",
        "issue_comment",
        "pull_request_review_comment",
    ]
    assert re.findall(r"types: \[(.*?)\]", on) == ["labeled", "created", "created"]


def test_gate_has_one_branch_per_trigger() -> None:
    assert sorted(_branches()) == ["issue_comment", "issues", "pull_request_review_comment"]


@pytest.mark.parametrize(
    "fn", ["startsWith(", "endsWith(", "format(", "fromJSON(", "toJSON(", " != "]
)
def test_gate_uses_no_fuzzy_or_negated_comparisons(fn: str) -> None:
    assert fn not in _job_if()


def test_identities_and_labels_use_exact_equality() -> None:
    gate = _job_if()
    # contains() is used only for the label list and the trigger phrase.
    for arg in re.findall(r"contains\(([^,]+),", gate):
        assert arg in ("github.event.issue.labels.*.name", "github.event.comment.body"), arg
    # Every login, type, label, or action is compared with == to a literal.
    for field in re.findall(r"github\.event\.[\w.]*(?:login|type|label\.name|action)\b", gate):
        assert re.search(re.escape(field) + r" == '[^']+'", gate), field


@pytest.mark.parametrize(
    ("branch", "required"),
    [
        (
            "issues",
            [
                "github.event.action == 'labeled'",
                "github.event.label.name == 'agent-go'",
                "github.event.sender.login == 'Reid-n0rc'",
                "github.event.sender.type == 'User'",
                "contains(github.event.issue.labels.*.name, 'plan-approved')",
                "contains(github.event.issue.labels.*.name, 'lane:site')",
                "github.event.issue.assignee",
            ],
        ),
        (
            "issue_comment",
            [
                "github.event.action == 'created'",
                "github.event.comment.user.login == 'Reid-n0rc'",
                "github.event.comment.user.type == 'User'",
                "github.event.comment.author_association == 'OWNER'",
                "github.event.issue.user.login == 'claude[bot]'",
                "contains(github.event.issue.labels.*.name, 'plan-approved')",
                "contains(github.event.issue.labels.*.name, 'lane:site')",
            ],
        ),
        (
            "pull_request_review_comment",
            [
                "github.event.action == 'created'",
                "github.event.comment.user.login == 'Reid-n0rc'",
                "github.event.comment.user.type == 'User'",
                "github.event.comment.author_association == 'OWNER'",
                "github.event.pull_request.user.login == 'claude[bot]'",
                "github.event.pull_request.head.repo.full_name == github.repository",
            ],
        ),
    ],
)
def test_each_branch_checks_identity_and_scope(branch: str, required: list[str]) -> None:
    text = " ".join(_branches()[branch].split())
    for condition in required:
        assert condition in text, f"{branch}: missing {condition}"


def test_run_time_recheck_runs_before_claude() -> None:
    recheck = TEXT.index("- name: Re-check the trigger at run time")
    claude = TEXT.index("uses: anthropics/claude-code-action@")
    assert recheck < claude
    step = TEXT[recheck:claude]
    assert "set -euo pipefail" in step
    assert '.user.login == "claude[bot]"' in step
    assert ".head.repo.full_name == $repo" in step
    assert '"agent-go"' in step
    assert "exit 1" in step


def test_permissions_are_minimal() -> None:
    assert "\npermissions: {}\n" in TEXT
    writes = re.findall(r"^\s+([a-z-]+): write$", TEXT, re.MULTILINE)
    assert writes == ["id-token"]


def test_every_action_is_pinned_to_a_full_sha() -> None:
    uses = re.findall(r"uses: (\S+)", TEXT)
    assert uses
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref


def test_claude_cannot_merge_tag_release_or_relabel() -> None:
    disallowed = re.search(r'--disallowedTools "([^"]+)"', TEXT)
    assert disallowed
    tools = disallowed.group(1).split(",")
    for tool in (
        "Bash(gh pr merge:*)",
        "Bash(gh pr review:*)",
        "Bash(gh issue edit:*)",
        "Bash(gh label:*)",
        "Bash(gh release:*)",
        "Bash(gh api:*)",
        "Bash(git tag:*)",
        "Edit(.github/**)",
    ):
        assert tool in tools, tool
