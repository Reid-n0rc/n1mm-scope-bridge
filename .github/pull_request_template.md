Closes #

## Summary

## Regression testing
<!-- Commands run and their results (see AGENTS.md → Testing policy). -->

## Hardware testing
<!-- Radio model + firmware, N1MM+ version, what you saw. "Not applicable" if none. -->

## Checklist
- [ ] Branch is `issue-<n>-<slug>`, based on `dev`, and the PR targets `dev`
- [ ] Linked issue has the `plan-approved` label and is assigned
- [ ] Issue has a `lane:*` label, and `python scripts/check_overlap.py <issue>` was clear when work started (AGENTS.md → Parallel work)
- [ ] Follows [STYLE.md](../STYLE.md) (naming, messages, docs, commit/PR format)
- [ ] Diff stays within the issue's plan (about 300 lines and 5 files or fewer; follow-ups filed as new issues)
- [ ] Every new or changed function has thorough tests (happy path, edge cases, invalid input, errors)
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest --cov` passes
- [ ] Changelog fragment added (`changelog.d/<issue>.<type>.md`), or the PR has the `no-changelog` label
- [ ] New regression checks are new files in `scripts/regression_steps/` (no edits to `release_regression.py`)
- [ ] User-facing changes are documented in `docs/user/` (and the website), per AGENTS.md → Documentation
- [ ] Code ported from wfview or elsewhere is credited in a header comment and in THIRD_PARTY.md
- [ ] No FTDI libraries, oversized captures, or secrets included

<!-- Release PRs (dev → master) only: -->
- [ ] Release PR: **Release regression** is green on Windows (link the run, paste `regression-report.md`), CHANGELOG updated
- [ ] Release PR: RC on-air check with FT-710 + N1MM+ is planned (AGENTS.md → Release process)
