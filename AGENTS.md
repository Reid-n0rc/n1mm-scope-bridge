# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex, Copilot, Cursor, and
others) and for human contributors. `CLAUDE.md` points here, so this file is
the single source of truth. If another doc disagrees with this one, this one
wins. Fix the other doc in the same PR.

## Project

`n1mm-scope-bridge` reads a radio's spectrum scope and sends it to N1MM
Logger+'s Spectrum Display window as N1MM's external `<Spectrum>` UDP packet.
The first radio is the **Yaesu FT-710**. Its scope arrives through an FTDI
FT4222 USB-to-SPI bridge, which is separate from the CAT COM ports.

- Stack: Python 3.10 or later, standard library only at runtime (`ctypes`,
  `socket`, `argparse`), and uv, pytest, ruff, and mypy (strict) for development
- Commands:
  - `uv sync`: create `.venv` with the dev tools
  - `uv run pytest --cov`: unit tests. Coverage must stay at 90% or higher.
  - `uv run ruff check . && uv run ruff format --check .`: lint and format
  - `uv run mypy`: strict type check of `src/` and `tests/`
  - `sh tests/hooks/run.sh`: git hook and agent hook tests
- Follow [STYLE.md](STYLE.md) for code, messages, docs, GUI, website, and git conventions.
- Read these before touching the matching area:
  - [docs/architecture.md](docs/architecture.md): module layout and data flow
  - [docs/protocol-yaesu-ft4222.md](docs/protocol-yaesu-ft4222.md): FT-710 frame layout
  - [docs/n1mm-spectrum-protocol.md](docs/n1mm-spectrum-protocol.md): N1MM packet
  - [docs/adding-a-radio.md](docs/adding-a-radio.md): how a new radio plugs in

## Product target

- **Windows 10/11 x64 is the product platform**, because N1MM Logger+ runs only
  on Windows. Operators install with the Windows installer and use the GUI;
  they never need Python or a terminal.
- **Every user-facing feature is usable from the GUI.** The CLI exists for
  scripts, headless station PCs, and troubleshooting.
- **Windows CI is required** for every supported Python (3.10, 3.13, and
  free-threaded 3.14t), as is the Windows release regression (app, GUI
  self-test, and installer install/run/uninstall).
- **Keep the code portable.** Ubuntu CI and one macOS job stay so the core
  keeps working elsewhere for possible future uses, but macOS and Linux are
  unsupported for operators. Keep platform-specific code behind small seams
  (for example the FTDI library names in `transport/ft4222.py`), and use Qt
  (PySide6) for the GUI.

## Non-negotiable rules

1. **No work without an approved, assigned issue.** Every change is tracked by
   a GitHub issue that contains a software plan. Do not start until the
   maintainer (@Reid-n0rc) approves the plan, which means the issue has the
   `plan-approved` label. Issues labeled `plan-needs-approval` are **not**
   ready. Before work starts, assign the issue to whoever is working it.
2. **One branch per issue, based on `dev`.**
   ```bash
   git fetch origin
   git switch -c issue-<number>-<short-slug> origin/dev
   ```
3. **Open pull requests against `dev`.** Never push directly to `dev` or
   `master`. A ruleset enforces this. PRs from non-admins need code-owner
   approval, and new pushes dismiss approvals.
4. **Only the maintainer promotes `dev` to `master`**, through a release PR.
   Tags and releases come only from `master`.
5. **Do not push, tag, release, or bump versions** unless the maintainer
   explicitly asks in the current conversation. Commit locally and stop.
6. **Respect licenses (GPL-3.0-only).** wfview is GPLv3. Code ported or
   adapted from it is allowed only with all of the following, in the same PR
   (GPLv3 §§4–5, enforced by `tests/test_licensing.py`):
   - wfview's copyright notices kept **verbatim** in the file header (copy them
     from `NOTICE`), plus `SPDX-FileCopyrightText` lines for both copyright
     holders;
   - the GPL notice block, and a dated **"Modified by <name>, <YYYY-MM-DD>:
     <what changed>"** notice;
   - a row in the derived-files table in [THIRD_PARTY.md](THIRD_PARTY.md).

   Use `src/n1mm_scope_bridge/radios/yaesu_scope.py` as the template. Never
   copy code from sources whose license is unknown or incompatible, such as
   proprietary SDKs, Yaesu documents beyond facts, or N1MM binaries. Every
   `.py` file starts with `SPDX-License-Identifier` and
   `SPDX-FileCopyrightText` lines. Releases must ship `LICENSE`, `NOTICE`,
   and `THIRD_PARTY.md`, with the sdist attached next to any binary (§6).
7. **Never commit or bundle FTDI libraries** (LibFT4222, ftd2xx), not even in
   release builds. They are proprietary and not GPL-compatible. Users install
   them from FTDI. The `pre-commit` hook blocks them.
8. **Never transmit, and never key the radio.** This project only reads scope
   data. Do not add code that sends CAT commands that change radio state
   unless an approved issue says so explicitly.
9. **Test everything, and regress before merging.** See the Testing policy.
10. **Sign commits when possible** (SSH or GPG). Signing is encouraged, not
    required.

## Task sizing (context-window budget)

**Always break work up so that one agent session can finish it without
exceeding its context window.** This applies to issues, to plans, and to how
an agent works inside a session.

- One issue covers one concern: one module, one radio, one doc, or one
  workflow.
- Aim for a diff of **300 lines or fewer** (tests excluded), touching **5 files
  or fewer**.
- A plan must list every file the issue reads or changes. If doing the work
  means reading more than about **10 files**, or any very large file, split
  the issue.
- **Do not load large inputs into context.** wfview is a large Qt codebase.
  Read only the specific function or file named in the issue, for example
  `src/radio/yaesucommander.cpp` `haveScopeData()` or
  `src/ft4222handler.cpp`. Never read the whole tree. Scope captures used as
  fixtures must be a few frames (the hook rejects files over 1 MiB). Never
  paste a full capture into context. Inspect it with a script that prints a
  summary.
- If a task grows mid-flight, **stop**. Commit what is coherent, then open a
  follow-up issue with its own plan for approval. Do not expand scope.
- Agents that spawn sub-agents should give each one an issue-sized piece, not
  the whole project.

## Local setup

```bash
uv sync
git config core.hooksPath .githooks
```

- `pre-commit` blocks commits on `master` or `dev`, staged FTDI vendor
  libraries, and staged files over 1 MiB.
- `pre-push` blocks pushes to `master` or `dev`. The maintainer-only emergency
  bypass is `ALLOW_PROTECTED_PUSH=1`.
- `.claude/settings.json` wires in `.claude/hooks/guard-git-push.sh`, which
  needs `jq`. It denies agent pushes to `master` or `dev` and force pushes,
  except `--force-with-lease` on `issue-*` branches.

## Issue lifecycle

Anyone can file a **Bug report**, **Feature request**, or **Radio support
request** without a plan. Those templates are intake only, and filing one
does not authorize work.

1. Before anyone works an issue, it needs a software plan: the goal, the
   steps, every file it touches, a test plan, acceptance criteria, and what is
   out of scope. New work uses the **Implementation task** template. Then apply
   `plan-needs-approval`.
2. The maintainer approves the plan by swapping the label to `plan-approved`,
   or asks for changes in the comments.
3. Assign the issue (`gh issue edit <n> --add-assignee @me`). Agents act
   under the maintainer's account, so agent work is assigned to that account.
4. Work on `issue-<n>-<slug>`, branched from `dev`.
5. Open a PR into `dev` whose body contains `Closes #<n>`. The **Issue policy**
   check (`.github/workflows/issue-policy.yml`) fails a PR whose linked issue
   lacks `plan-approved` or an assignee. CI must be green.
6. The maintainer (or an agent the maintainer has explicitly authorized)
   merges.

Hardware-dependent findings (anything learned by running against a real
radio) go in the issue as a comment, with the radio model, the firmware
version, and a short trimmed capture, so the result can be reproduced.

## Parallel work (no PR conflicts)

Several people or agents can work at once without PR conflicts if these rules
hold (#43):

1. **Every issue has one lane label:** `lane:core` (bridge, transport,
   emulator, CLI internals), `lane:gui`, `lane:packaging` (build, installer,
   release, CI packaging), `lane:site` (website and user-docs content), or
   `lane:process` (shared infrastructure).
2. **At most one open PR per lane.** `lane:process` work runs alone: it touches
   shared files, so other lanes wait for it to merge.
3. **Check for overlap before starting.** Run
   `python scripts/check_overlap.py <issue>`. It compares the issue's **Files**
   list with the files changed by every open PR. Start only if it reports
   *Clear to start*; otherwise wait for the other PR, or stack on it
   deliberately and say so in your PR. The **PR overlap** workflow also posts
   a warning on any PR that shares files with another open PR.
4. **Prefer new files to shared ones.** Add a CLI command as its own module,
   a regression step as its own file, and a changelog entry as a fragment
   (see #44 and #45) instead of editing a shared list.
5. **Merge bottom-up as soon as CI is green.** Then bring dependent branches
   up to date with `git merge origin/dev`. Never rebase or force-push a
   branch someone else may have.
6. **Use a separate git worktree per agent**
   (`git worktree add ../n1mm-wt-<lane> -b issue-<n>-<slug> origin/dev`) so
   parallel agents never share a checkout.

## Automated PRs

Copilot Autofix, Dependabot, and any other bot get **no exemption** from the
**Issue policy** and **Changelog** checks, or from review of what they change.
Copilot's repository instructions are in
[.github/copilot-instructions.md](.github/copilot-instructions.md).

- **Adopt it.** File (or link) a `plan-approved`, assigned issue and add
  `Closes #<n>` to the PR body. Add the `changelog.d/` fragment, and push any
  fixes to the PR branch through the normal process. Then CI runs on the
  pushed commit and the PR merges like any other.
- **Or replace it.** Close the bot's PR with a comment linking a tracked PR that
  does the work properly. Do this when its change is wrong or incomplete, for
  example when it rewrites an intentional pattern.
- A bot never satisfies the checks on its own behalf. No labels, edits, or
  exemptions are added just to get its PR through.

## Testing policy

0. **No automated test may need a radio.** Use the FT-710 emulator
   ([docs/emulator.md](docs/emulator.md)), captures, or fakes. Only
   `@pytest.mark.hardware` tests touch a real radio.
1. **Every function has thorough unit tests**: the happy path, boundaries,
   invalid input, and every error path. Tests never need a radio, FTDI
   libraries, N1MM, or the network. Use synthetic frames built in the test,
   small binary fixtures under `tests/fixtures/`, a fake `ctypes` library
   object, and a fake or loopback socket.
2. **Hardware tests are opt-in.** Mark them `@pytest.mark.hardware`. They are
   skipped unless `N1MM_BRIDGE_HARDWARE=1` is set, and they never run in CI.
   Record their results in the issue or PR.
3. **Every change runs regression tests.** Before opening or updating a PR,
   run the full suite plus lint and type checks. Paste the commands and
   results into the PR. Never skip, xfail, or delete a failing test to get
   green.
4. **Every release runs full regression from a clean environment**, and the
   maintainer runs an on-air check with a real FT-710 and N1MM+:
   ```bash
   uv sync --locked && uv run ruff check . && uv run ruff format --check . \
     && uv run mypy && uv run pytest --cov && sh tests/hooks/run.sh
   ```

## Code conventions

- Source goes in `src/n1mm_scope_bridge/` and tests in `tests/`, with module
  names mirrored (`foo.py` → `tests/test_foo.py`).
- Every file starts with `# SPDX-License-Identifier: GPL-3.0-only` and a
  `# SPDX-FileCopyrightText:` line.
- **CLI commands:** one module per command in
  `src/n1mm_scope_bridge/cli/commands/` (the contract is in that package's
  `__init__.py`), with tests in `tests/cli/test_cli_<name>.py` and a page in
  `docs/user/cli/<name>.md`. Shared helpers go in `cli/common.py`. Commands
  are discovered automatically, so never register one in a shared list.
- Keep parsing **pure**: functions that turn `bytes` into dataclasses, with no
  I/O. Keep I/O (the FT4222 device, sockets, files) in thin adapters behind
  small protocols, so tests can substitute fakes.
- Radios plug in through a `RadioProfile` plus a `SpectrumSource`. See
  [docs/adding-a-radio.md](docs/adding-a-radio.md). Do not special-case a
  radio model outside its own module.
- Anything derived from wfview follows rule 6 (verbatim notices, GPL block,
  dated modification notice, THIRD_PARTY.md row).
- Mark anything not yet confirmed on real hardware with `# UNVERIFIED:` and
  link the hardware-validation issue.
- **Concurrency** (see docs/architecture.md, Concurrency):
  - No blocking I/O on the process or sender threads. Only the reader stage
    talks to the device.
  - No shared mutable state between pipelines or module-level mutable
    globals. Frames passed between threads are immutable (frozen dataclasses,
    tuples, bytes).
  - All threads are non-daemon, named `<radio>-<stage>`, and joined on
    shutdown. Tests check that no threads leak.
  - Code must be correct on free-threaded CPython (3.14t, in CI). Never rely on
    the GIL for atomicity.
  - Synchronize threaded tests with events, never with sleeps alone.
- Never log at a rate higher than once per second inside the frame loop. The
  radio produces dozens of frames per second.
- Default N1MM update rate: about 3 to 5 packets per second, never more than
  10. This follows the N1MM team's guidance.

## Documentation

**Every user-facing change updates the user documentation in the same PR.**
That covers a CLI command or option, a setting, a GUI behaviour, a UDP
control command, or an error message. The user docs live in `docs/user/`,
and the website (#21–#23) is rendered from them.

`tests/test_docs.py` fails CI when:
- a command lacks its page `docs/user/cli/<command>.md`, an option is missing
  from its command's page, or a setting is missing from `settings.md`;
- a user-facing error message is missing from `troubleshooting.md`;
- a link is broken.

New error messages go into `USER_MESSAGES` in that test.

## Release process

Releases are gated by the **full release regression**
(`scripts/release_regression.py`, workflow `Release regression`). It runs
automatically on every PR into `master` and on every `v*` tag, and on demand:

```bash
uv run --no-project python scripts/release_regression.py --report regression-report.md
# off Windows (development only, not releasable):
uv run --no-project python scripts/release_regression.py --skip-windows-only
```

It covers: a locked clean environment, lint, format, strict mypy, every test
including slow and licensing tests with coverage, hook tests, sdist and wheel
build plus content checks (licenses, source, no FTDI binaries), a wheel
install smoke test, end-to-end replay, every emulator scenario, and (as each
feature lands) the Windows app, the GUI self-test, the installer
install/run/uninstall, and the website build. A Windows run with no skipped
Windows steps is required.

**Every new user-facing feature adds its regression step in the same PR, as
its own file** in `scripts/regression_steps/NN_name.py` (see the README
there). The runner discovers step files in filename order, so nobody edits
`release_regression.py` to add a check. Each lane owns its placeholder file
(`70_windows_app.py`, `75_gui_self_test.py`, `80_installer.py`,
`90_website.py`).

**Every PR into `dev` adds a changelog fragment**,
`changelog.d/<issue>.<type>.md` (see `changelog.d/README.md`), instead of
editing `CHANGELOG.md`. The **Changelog** check enforces this unless the PR
has the `no-changelog` label.

1. **Release candidate.** Open a PR from `dev` to `master` titled
   `Release vX.Y.Z`. The maintainer chooses the version. The Release
   regression must be green on Windows. Paste its report (job summary or
   artifact) into the PR, and run
   `python scripts/build_changelog.py --version X.Y.Z` to fold the fragments
   into [CHANGELOG.md](CHANGELOG.md).
2. The maintainer merges, then tags `vX.Y.Z-rc1` on `master`. The regression
   runs again on the tag, and the release workflow publishes a GitHub
   **pre-release**.
3. **On-air check.** The maintainer installs the RC on the station PC and
   verifies the waterfall with a real FT-710 and N1MM+. Fixes go through
   `dev` as usual, followed by another RC.
4. **Release.** The maintainer tags `vX.Y.Z` on the same commit as the
   accepted RC. The regression runs on the tag, and the release and website
   publish.
5. Agents never tag, release, or bump versions.
