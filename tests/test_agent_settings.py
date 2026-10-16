# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The committed Claude Code permission rules keep their safety denies (#221).

``.claude/settings.json`` must deny an agent approving its own plan, merging
with ``--admin``, approving the release deployment gate (#233, #234), any
GraphQL call, and any ``gh api`` write, in every spelling we know of. The
globs are matched the way Claude Code matches ``Bash(...)`` rules: ``*`` stands
for any text, the whole command must match, and rules are checked deny first,
then ask, then allow. These rules are best-effort; the real gates are
server-side (see AGENTS.md, Local setup).
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


def _asked(command: str) -> bool:
    return any(_matches(rule, command) for rule in _rules("ask"))


def _allowed_one(command: str) -> bool:
    if _denied(command) or _asked(command):
        return False
    return any(_matches(rule, command) for rule in _rules("allow"))


def _allowed(command: str) -> bool:
    """Runs with no prompt: Claude Code checks deny, then ask, then allow.

    Claude Code splits compound commands on shell operators, so every part
    must be allowed on its own; a substitution (``$(``, backticks) or a
    redirect always prompts.
    """
    if _denied(command) or _asked(command):
        return False
    if any(token in command for token in ("$(", "`", ">", "<")):
        return False
    parts = [part.strip() for part in re.split(r"&&|\|\||[;&|\n]", command)]
    return all(part and _allowed_one(part) for part in parts)


RUN = "repos/Reid-n0rc/n1mm-scope-bridge/actions/runs/123"
DEPLOY = "repos/Reid-n0rc/n1mm-scope-bridge/deployments/45/statuses"
LABELS = "repos/Reid-n0rc/n1mm-scope-bridge/issues/12/labels"

DENIED = [
    # Approving or rejecting the release environment gate.
    f"gh api -X POST {RUN}/pending_deployments -f state=approved",
    f"gh api --method POST {RUN}/pending_deployments -F environment_ids[]=1",
    f"gh api --method=POST {RUN}/pending_deployments --input body.json",
    f"gh api {RUN}/pending_deployments --field state=approved",
    f"gh api {RUN}/pending_deployments -f state=rejected",
    f"gh api -XPOST /{RUN}/pending_deployments",
    f"gh api {RUN}/pending_deployments",
    # Writing a deployment status directly.
    f"gh api -X POST {DEPLOY} -f state=success",
    f"gh api --method POST {DEPLOY} --field state=success",
    f"gh api --method=POST {DEPLOY} --input status.json",
    f"gh api {DEPLOY} -f state=success",
    # Custom deployment protection rule callback.
    f"gh api -X POST {RUN}/deployment_protection_rule -f state=approved",
    # Any GraphQL call (addLabelsToLabelable, mergePullRequest, approveDeployments).
    "gh api graphql -f query='mutation { approveDeployments(input: {}) { clientMutationId } }'",
    "gh api graphql -F query=@mutation.graphql",
    "gh api graphql --input mutation.json",
    "gh api https://api.github.com/graphql --input q.json",
    # Any gh api write: an explicit method, or a field or body (implies POST).
    f"gh api -X PATCH {LABELS}",
    f"gh api -XPUT {LABELS}",
    f"gh api {LABELS} -X POST",
    f"gh api {LABELS} --method PUT",
    f"gh api {LABELS} --method=POST",
    f"gh api {LABELS} -f labels[]=lane:core",
    f"gh api {LABELS} -flabels[]=lane:core",
    f"gh api {LABELS} -F labels[]=@labels.txt",
    f"gh api {LABELS} --raw-field labels[]=lane:core",
    f"gh api {LABELS} --field=labels[]=lane:core",
    f"gh api {LABELS} --input labels.json",
    f"gh api -i -X POST {LABELS}",
    f"gh api -iX POST {LABELS}",
    f"gh api {LABELS} -if labels[]=lane:core",
    f"gh api {LABELS} -iF labels[]=lane:core",
    "gh api -X DELETE repos/o/r/git/refs/heads/dev",
    "gh api --method=delete repos/o/r/git/refs/heads/dev",
    "gh api -X=DELETE repos/o/r/git/refs/heads/dev",
    # Env prefixes and other paths to gh.
    f"GH_TOKEN=x gh api {LABELS} -f labels[]=x",
    f"command gh api {LABELS} --input l.json",
    f"/usr/local/bin/gh api -X POST {LABELS}",
    "GH_TOKEN=x gh release create v1.0.0",
    "/opt/homebrew/bin/gh release upload v1.0.0 x.exe",
    # Only the maintainer approves plans, in any spelling.
    "gh issue edit 12 --add-label plan-approved",
    "gh issue edit 12 --add-label=plan-approved",
    "gh issue edit 12 --add-label lane:core,plan-approved",
    "gh issue edit 12 --add-label PLAN-APPROVED",
    "gh issue edit 12 --add-label Plan-Approved",
    "gh issue create --title x --label plan-approved",
    "gh issue create --title x -l plan-approved",
    f"gh api {LABELS} -f 'labels[]=plan-approved'",
    "gh label edit plan-needs-approval --name plan-approved",
    "GH_TOKEN=x gh issue edit 12 --add-label plan-approved",
    # Never bypass the ruleset, in any flag order or spelling.
    "gh pr merge 230 --admin",
    "gh pr merge --admin 230 --auto",
    "gh pr merge 230 --merge --admin --auto",
    "gh pr merge 230 --admin=true",
    "gh pr merge 230 --auto=false --merge",
    "command gh pr merge --admin 230",
    # Indirection that would hide any of the above.
    "gh alias set ok 'api -X POST repos/o/r/issues/1/labels'",
    "gh auth token",
    "gh release create v1.0.0",
]

ASKED = [
    "gh pr merge 230 --auto --merge",
    "gh pr merge 230 --merge",
    "gh pr -R Reid-n0rc/n1mm-scope-bridge merge 230",
    "GH_TOKEN=x gh pr merge 230 --merge",
    "gh issue delete 12",
    "gh issue -R o/r delete 12",
    "gh issue transfer 12 o/other",
    "gh workflow run release.yml --ref dev -f tag=v0.1.0-rc1",
    "git tag v1.0.0",
]

NOT_DENIED = [
    "gh pr merge 230 --auto --merge",
    "gh pr view 230",
    "gh issue edit 12 --add-label lane:core",
    "gh issue edit 12 --remove-label plan-needs-approval",
    f"gh api {RUN}",
    "gh api repos/Reid-n0rc/n1mm-scope-bridge/pulls/230",
    "gh api repos/Reid-n0rc/n1mm-scope-bridge/pulls/230 --jq .state",
    "gh api --paginate repos/Reid-n0rc/n1mm-scope-bridge/code-scanning/alerts",
]


def test_settings_is_valid_json_with_all_rule_lists() -> None:
    for kind in ("allow", "ask", "deny"):
        assert _rules(kind), kind


@pytest.mark.parametrize(
    "rule",
    [
        "Bash(*pending_deployments*)",
        "Bash(*deployments/*/statuses*)",
        "Bash(*graphql*)",
        "Bash(*--admin*)",
        "Bash(*plan-approved*)",
        "Bash(*gh api * --input*)",
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


@pytest.mark.parametrize("command", ASKED)
def test_command_always_prompts(command: str) -> None:
    assert _asked(command) or _denied(command), command
    assert not _allowed(command), command


@pytest.mark.parametrize("command", DENIED + ASKED)
def test_no_risky_command_runs_without_a_prompt(command: str) -> None:
    assert not _allowed(command), command


@pytest.mark.parametrize(
    "command", ["gh pr view 230", "gh pr checks 230", "gh issue view 221", "gh run list --limit 5"]
)
def test_routine_command_runs_without_a_prompt(command: str) -> None:
    assert _allowed(command), command


NOT_ALLOWED = [
    # Subcommands outside the narrow allowlist fall to a prompt.
    "gh run cancel 123",
    "gh run delete 123",
    "gh issue edit 12 --add-label lane:core",
    "gh issue edit 12 --remove-label plan-needs-approval",
    "gh issue reopen 12",
    "gh issue lock 12",
    "gh issue pin 12",
    "gh issue develop 12 --checkout",
    "gh pr merge 1 --auto --delete-branch",
    "gh pr close 230",
    "gh pr edit 230 --base master",
    "gh pr ready 230",
    "gh pr comment 230 --body x",
    # A trailing glob never admits a chained or substituted command.
    "gh pr merge 1 --auto; rm -rf x",
    "python scripts/ready_to_merge.py 230; rm -rf x",
    "python scripts/ready_to_merge.py 230 && gh run cancel 1",
    "python scripts/check_overlap.py 221 | sh",
    "gh pr view 230 $(rm -rf x)",
    "gh pr view 230 `rm -rf x`",
    "gh issue view 12 > ~/.bashrc",
    "gh run view 1 & gh run delete 1",
    "gh issue list --limit 5\ngh issue delete 12",
]


@pytest.mark.parametrize("command", NOT_ALLOWED)
def test_command_outside_allowlist_prompts(command: str) -> None:
    assert not _allowed(command), command


def test_every_allow_rule_names_one_exact_subcommand() -> None:
    for rule in _rules("allow"):
        body = rule.removeprefix("Bash(").removesuffix(")")
        assert body.endswith(" *"), rule
        assert "*" not in body[:-2], rule
        assert len(body[:-2].split()) >= 2, rule


def test_chain_of_allowed_commands_is_allowed() -> None:
    assert _allowed("gh pr view 230 && gh pr checks 230")


def test_matcher_rejects_non_bash_rules() -> None:
    assert not _matches("Read(*)", "gh api x")
    assert _matches("Bash(gh api *)", "gh api x")
