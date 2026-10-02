# Instructions for GitHub Copilot

These apply to Copilot's coding agent, code review, and Autofix in this
repository. The full rules are in [AGENTS.md](../AGENTS.md) (process) and
[STYLE.md](../STYLE.md) (code and text style). Where they disagree with this
file, AGENTS.md wins.

## Every pull request

- **Target `dev`**, never `master`. Branch name: `issue-<n>-<slug>`.
- **Close an approved, assigned issue.** The PR body must contain
  `Closes #<n>`, where issue `#<n>` has the `plan-approved` label and an
  assignee. The **Issue policy** check fails otherwise. Don't open a PR without
  one; a maintainer will adopt or replace it.
- **Add a changelog fragment**: `changelog.d/<issue>.<type>.md`, where the type
  is `added`, `changed`, `fixed`, `removed`, `deprecated`, or `security` (code
  scanning fixes use `security`). It holds one plain-language line for an
  operator. Never edit `CHANGELOG.md`. See [changelog.d/README.md](../changelog.d/README.md).
- **Tests are required** for every changed function (happy path, edge cases,
  invalid input, errors). **No automated test may need a radio.** Use the
  FT-710 emulator (`n1mm_scope_bridge.emulator`), captures, or fakes.
- Run `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest --cov`.
- **Resolve every CodeQL alert and security finding the PR introduces** before
  it can merge: fix it, or explain a genuine false positive in the PR so a
  maintainer can dismiss it with a justification. The merge gate
  (`scripts/ready_to_merge.py`) refuses PRs with red checks, open CodeQL alerts,
  open secret-scanning alerts, or a failing dependency review.

## Never

- Never transmit, key the radio, or change radio state.
- Never commit or bundle FTDI libraries (LibFT4222, ftd2xx) or secrets.
- Never weaken a check, skip or delete a failing test, or bump a version.

## Licensing

- The project is **GPL-3.0-only**. Every `.py` file starts with
  `SPDX-License-Identifier` and `SPDX-FileCopyrightText` lines.
- Code derived from wfview keeps wfview's copyright notices verbatim, the GPL
  notice block, and a dated "Modified by" notice, and is listed in
  `THIRD_PARTY.md`. `tests/test_licensing.py` enforces this.

## Intentional patterns (do not "fix")

- `pipeline.Pipeline._guard` catches `BaseException` on purpose: any stage
  failure, including `KeyboardInterrupt`, must stop every stage and be
  re-raised from `join()`.
- The `KeyboardInterrupt` handler in the CLI's `supervise()` exists so Ctrl-C
  stops streaming cleanly.
- Threads must be named, non-daemon, and joined, and must never touch Qt
  widgets.

If a code scanning alert points at one of these, explain that in the PR
instead of changing the behaviour.
