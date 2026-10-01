# Style guide

How everything in this repository should look and read: code, messages,
docs, the GUI, the website, commits, and pull requests. Humans and AI agents
follow it alike. [AGENTS.md](AGENTS.md) holds the rules and process; this
file holds the conventions. Tooling enforces what it can (ruff, mypy, and
`tests/test_licensing.py`, plus `tests/test_docs.py` once the user docs land).
Everything else is checked in review.

When this guide and existing code disagree, follow the guide and fix the code
in a separate issue. Don't mix style sweeps into feature PRs.

## Language and terminology

- **US English**, matching the radio's own labels ("Center mode", "color").
- Use these names exactly:

  | Write | Not |
  |---|---|
  | N1MM+ (N1MM Logger+ on first use in a page) | N1MM, n1mm, N1MM Logger Plus |
  | FT-710, FTDX10, FTDX101 | FT710, ft-710 (except the CLI key `ft710`) |
  | wfview | WFView, WfView |
  | FTDI LibFT4222, D2XX | ft4222 lib, the FTDI DLL |
  | FT4222 (the chip) | 4222 |
  | Spectrum Display (N1MM's window) | spectrum window, bandmap |
  | scope (the radio's panadapter/waterfall) | panadapter, spectrum scope (mixing terms) |
  | source name (what N1MM+ lists) | spectrum name, ID |
  | Center / Cursor / Fixed mode (scope modes) | centre, centered mode |
  | system tray | notification area, taskbar tray |
  | emulator | simulator, mock radio |

- **Units:** a space between number and unit; SI prefixes as shown.
  - Frequencies: `14.074000 MHz` (6 decimals) in status lines, `14.074 MHz` in prose; `kHz` for spans (`20 kHz`); `Hz` in protocol docs and raw values.
  - Rates: `4 updates/s`; frame rates `frames/s`.
  - Sizes: `4096 bytes`, `1 MiB` (binary prefixes for memory and file sizes).
  - Time: `100 ms`, `2 s`.
- Code identifiers keep code spelling (`ScopeStatus`, `--rate`) and go in
  backticks in prose.

## Python code

- **Formatting and linting:** `ruff format` and `ruff check` (config in
  `pyproject.toml`; line length 100). Don't argue with the formatter. If a
  line reads badly, restructure it.
- **Types:** `mypy --strict` must pass. Use `from __future__ import annotations`
  in every module. Prefer `X | None` over `Optional[X]`, built-in generics
  (`list[int]`), and `collections.abc` for `Callable`, `Iterable`, and
  `Iterator`. Add a `# type: ignore[code]` only with a specific code and a reason.
- **File header:** the first lines of every `.py` file:
  ```python
  # SPDX-License-Identifier: GPL-3.0-only
  # SPDX-FileCopyrightText: 2026 <Name, call sign>
  ```
  wfview-derived files add the full notice block (AGENTS.md rule 6; use
  `src/n1mm_scope_bridge/radios/yaesu_scope.py` as the template).
- **Module docstring:** one sentence saying what the module is for, then any
  design notes and references (doc paths, issue numbers).
- **Docstrings:** triple double quotes. The summary line is imperative or
  descriptive and ends with a period. Document behaviour, units, thread-safety,
  and what is raised, not the obvious. Attribute docstrings sit on the line
  after a dataclass field when the meaning isn't obvious.
- **Comments** explain *why*. Mark facts not yet confirmed on hardware with
  `# UNVERIFIED (#<issue>): …`. No commented-out code and no `TODO` without an
  issue number (`# TODO(#42): …`).
- **Naming:** `snake_case` functions and variables, `PascalCase` classes,
  `UPPER_SNAKE` module constants with units in the name when ambiguous
  (`READ_TIMEOUT_MS`, `DEFAULT_RATE_HZ`). Private helpers start with `_`.
  Booleans read as predicates (`is_open`, `edges_verified`).
- **Data:** immutable by default: `@dataclass(frozen=True)`, tuples, and `bytes`.
  Mutable state lives inside one class behind its lock.
- **Structure:** a pure core and thin I/O (docs/architecture.md). Parsing,
  encoding, and decisions are pure functions. Devices, sockets, files, and
  clocks are injected as keyword-only parameters with real defaults
  (`clock=time.monotonic`, `loader=_default_loader`) so tests substitute fakes.
- **Imports:** absolute (`from n1mm_scope_bridge.radios.base import …`), at
  the top of the file, sorted by ruff. The only lazy import allowed is an
  optional dependency (PySide6), behind a clear error.
- **Dependencies:** the runtime is the standard library only, except the
  optional `gui` extra. A new dependency needs an issue that records its
  license in THIRD_PARTY.md.
- **Platform code** sits behind a small seam (a function or protocol), never
  `if sys.platform` scattered through the logic. Windows is the supported
  platform. Keep the rest portable.

## Concurrency

- Threads are non-daemon, named `<radio>-<stage>` (or a clear name such as
  `control`), and joined on shutdown.
- Never touch Qt widgets off the GUI thread. Cross threads with queued
  signals.
- Never block the device reader. Hand-offs drop the oldest item, not the
  newest.
- Never rely on the GIL. Code must be correct on free-threaded CPython.
- Every loop that waits on hardware has a bound (timeout, retry limit) and
  checks the stop flag.

## Errors and messages

- **One exception type per failure domain** (`Ft4222Error`, `CaptureError`,
  `FrameError`, `UserError`). Subclass built-ins when that fits (`FrameError(ValueError)`).
- **User-facing messages** are one sentence, or two: what happened, then what
  to do.
  - Write `Could not open 'FT4222 A' (FT_DEVICE_NOT_FOUND). Is the radio on and connected by USB?`
  - Not `Error 2` or `Exception in open()`.
  - Start with a capital letter. Quote names with `'…'` (repr). Include the
    status name, not only the number.
  - No exclamation marks, no blame ("you did"), and no stack traces for
    problems a user can fix.
- The CLI prefixes `error: ` and `warning: ` (lower case, as argparse does) and
  exits `1` for user-fixable problems and `2` for usage errors.
- Validation messages name the field and the rule:
  `n1mm_port: port must be 1-65535 (N1MM+ uses 13064)`.
- Every user-facing message appears in `docs/user/troubleshooting.md`
  (enforced once the user-docs tests land).
- Inside the frame loop, log no more than once per second (`RateLimiter`).

## Writing for users

These rules apply to docs, the GUI, the website, and CLI help.

- Address the operator as **you**, in the active voice. Be short and concrete.
  Hams are technical, but not necessarily programmers.
- **Sentence case** for headings, buttons, menu items, labels, and dialog
  titles ("Start streaming", "Keep running in tray", "FTDI library folder").
- Buttons say what they do, with a verb: **Start streaming**, **Stop**,
  **Keep running in tray**, **Exit**, **Cancel**. Avoid OK and Yes/No when a
  verb fits.
- Explain *why* only where it changes what the user does (for example, why the
  FTDI library isn't bundled).
- Never promise unreleased features as available. Mark them **In
  development**, and link the issue in developer docs.

## Markdown docs

- One `# Title` per file in sentence case, then `##` and `###`, without
  skipping levels.
- Wrap prose at about 78 columns. Don't wrap tables, URLs, or code.
- Use fenced code blocks with a language (`bash`, `python`, `xml`). Show
  commands without a prompt, and Windows commands as they would be typed in
  PowerShell or cmd.
- Use tables for options, settings, and error catalogues, with columns in the
  order **name, default, meaning**.
- Use relative links inside the repo. Absolute URLs in angle brackets or
  link text, never bare.
- Use `**bold**` for UI labels the user clicks (**Window → Spectrum
  Display**), `` `code` `` for anything typed, and → for menu paths.
- Every doc says what version or state it describes when that matters
  (user docs are on the branch; the website is the latest release).

## GUI (Qt / PySide6)

- **Look:** native and modern. Use the `windows11` style on Windows and
  `Fusion` elsewhere. Follow the system light/dark setting. Never hard-code
  colours: use palette roles (`QPalette`) or one small application stylesheet
  in `gui/` that only uses palette references.
- **Layout:** `QFormLayout` for settings (labels on the left, ending without a
  colon in Windows 11 style), with grouping by `QGroupBox` titles in sentence
  case. Spacing comes from Qt defaults. No fixed pixel sizes except minimum
  window sizes. High-DPI is automatic, so never scale by hand.
- **Behaviour:** the window opens on start. Close asks (keep in tray or exit)
  unless the choice was remembered. Minimize goes to the tray and keeps
  streaming (#19). Long operations never block the GUI thread.
- **Feedback:** a status chip (Stopped / Streaming / Error), inline validation
  under the field, and dialogs only for errors that stop streaming.
- Icons come from one set (the app icon plus Qt standard icons). Every
  interactive control has an accessible name and a tooltip when its label is
  terse.

## Website

- Semantic HTML5 and one CSS file, with no JavaScript framework. Light and dark
  through `prefers-color-scheme`, defined with CSS custom properties.
- Readable at 360 px wide. Lighthouse accessibility 95 or higher. Every image
  has alt text. Screenshots come from the released build (#22).
- Content matches the **latest release** only (#21) and follows the user
  writing rules above.

## Tests

- Mirror module names: `src/…/foo.py` → `tests/test_foo.py`.
- Name tests by behaviour: `test_misaligned_stream_resyncs_on_inter_frame_pattern`,
  not `test_resync_2`.
- One behaviour per test; parametrize variations (`@pytest.mark.parametrize`
  with readable ids).
- No real radio, network, FTDI library, or N1MM+. Use the emulator,
  `tests/fakes.py`, `tests/frames.py`, and trimmed fixtures (under 1 MiB).
- Synchronize threaded tests with events or `qtbot.waitSignal`, never with
  sleeps alone. Every test finishes well under the 60 s `pytest-timeout`.
- Markers: `slow`, `gui`, `hardware` (opt-in, never in CI), and `native`
  (mock DLL).
- Assert on observable behaviour (output, packets, signals), not private
  attributes, unless testing a private helper directly.

## Git

- **Branches:** `issue-<n>-<short-slug>` from `dev`, for example
  `issue-38-style-guide`.
- **Commits:** a subject in the imperative, sentence case, no full stop,
  72 characters or fewer ("Add LibFT4222 ctypes reader with frame resync").
  Then a blank line, then a body explaining what and why, as bullets for
  multi-part changes, wrapped at 72. Put `Closes #<n>` in the body of the
  final commit. Trailers last. Sign commits when possible.
- **Pull requests:** the title equals the main commit subject. The body
  follows the template: `Closes #<n>`, Summary, Regression testing (commands
  and results), Hardware testing. Note stacked PRs at the top ("**Stacked on
  #N.**").
- **Issues:** titles are short noun phrases or imperatives, in sentence case.
  Implementation issues use the task template sections: Goal, Software plan,
  Files, Test plan, Acceptance criteria, Out of scope.

## Files and names

- Python modules: `snake_case.py`. Docs: `kebab-case.md`, except the
  conventional upper-case root files (`README.md`, `AGENTS.md`, `STYLE.md`, …).
- Scripts in `scripts/` are runnable (`uv run python scripts/<name>.py`), have a
  module docstring with usage, and use the standard library only unless they
  import the package.
- Test fixtures go in `tests/fixtures/`, with a name that says what they are
  (`ft710_synthetic.cap`). Generated fixtures have a regenerating script.
