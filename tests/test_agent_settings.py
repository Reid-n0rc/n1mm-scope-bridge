# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The committed Claude Code permission rules keep their safety denies (#221).

``.claude/settings.json`` must deny an agent approving its own plan, merging
with ``--admin``, or approving the release deployment gate (#233, #234). The
globs are matched the way Claude Code matches ``Bash(...)`` rules: ``*`` stands
for any text, and the whole command must match.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / ".claude" / "settings.json"


def _rules(kind: str) -> list[str]:
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    rules = data["permissions"][kind]
    assert isinstance(rules, list)
    return [str(rule) for rule in rules]


def _matches(rule: str, command: str) -> bool:
    match = re.fullmatch(r"Bash\((.*)\)", rule)
    if match is None:
        return False
    pattern = ".*".join(re.escape(part) for part in match.group(1).split("*"))
    return re.fullmatch(pattern, command, re.DOTALL) is not None


def _denied(command: str) -> bool:
    return any(_matches(rule, command) for rule in _rules("deny"))


RUN = "repos/Reid-n0rc/n1mm-scope-bridge/actions/runs/123"
DEPLOY = "repos/Reid-n0rc/n1mm-scope-bridge/deployments/45/statuses"

DENIED = [
    # Approving or rejecting the release environment gate.
    f"gh api -X POST {RUN}/pending_deployments -f state=approved",
    f"gh api --method POST {RUN}/pending_deployments -F environment_ids[]=1",
    f"gh api --method=POST {RUN}/pending_deployments --input body.json",
    f"gh api {RUN}/pending_deployments --field state=approved",
    f"gh api {RUN}/pending_deployments -f state=rejected",
    f"gh api -XPOST /{RUN}/pending_deployments",
    # Writing a deployment status directly.
    f"gh api -X POST {DEPLOY} -f state=success",
    f"gh api --method POST {DEPLOY} --field state=success",
    f"gh api --method=POST {DEPLOY} --input status.json",
    f"gh api {DEPLOY} -f state=success",
    # Custom deployment protection rule callback and the GraphQL mutation.
    f"gh api -X POST {RUN}/deployment_protection_rule -f state=approved",
    "gh api graphql -f query='mutation { approveDeployments(input: {}) { clientMutationId } }'",
    # Only the maintainer approves plans or bypasses the merge ruleset.
    "gh issue edit 12 --add-label plan-approved",
    "gh issue edit 12 --add-label lane:core,plan-approved",
    "gh issue create --title x --label plan-approved",
    "gh issue create --title x -l plan-approved",
    "gh pr merge 230 --admin",
    "gh pr merge --admin 230 --auto",
    "gh pr merge 230 --merge --admin --auto",
    # Releases and deletes.
    "gh release create v1.0.0",
    "gh api -X DELETE repos/o/r/git/refs/heads/dev",
    "gh api --method=delete repos/o/r/git/refs/heads/dev",
]

NOT_DENIED = [
    "gh pr merge 230 --auto --merge",
    "gh pr view 230",
    "gh issue edit 12 --add-label lane:core",
    f"gh api {RUN}",
    "gh api repos/Reid-n0rc/n1mm-scope-bridge/pulls/230",
]


def test_settings_is_valid_json_with_all_rule_lists() -> None:
    for kind in ("allow", "ask", "deny"):
        assert _rules(kind), kind


@pytest.mark.parametrize(
    "rule",
    [
        "Bash(gh api *pending_deployments*)",
        "Bash(gh api *deployments/*/statuses*)",
        "Bash(gh pr merge *--admin*)",
        "Bash(gh issue edit *--add-label*plan-approved*)",
    ],
)
def test_required_deny_rule_present(rule: str) -> None:
    assert rule in _rules("deny")


@pytest.mark.parametrize("command", DENIED)
def test_command_is_denied(command: str) -> None:
    assert _denied(command), command


@pytest.mark.parametrize("command", NOT_DENIED)
def test_routine_command_is_not_denied(command: str) -> None:
    assert not _denied(command), command


def test_no_allow_rule_permits_an_approval_endpoint() -> None:
    for command in DENIED:
        if "deploy" in command.lower():
            assert not any(_matches(rule, command) for rule in _rules("allow")), command


def test_matcher_rejects_non_bash_rules() -> None:
    assert not _matches("Read(*)", "gh api x")
    assert _matches("Bash(gh api *)", "gh api x")
