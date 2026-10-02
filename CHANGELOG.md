# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

See `changelog.d/` for changes not yet released.

## [0.1.0] - 2026-10-02

First release: the Yaesu FT-710's spectrum scope in N1MM Logger+'s Spectrum
Display on Windows, with a Qt GUI, an installer, and a built-in emulator.
Validated on a real FT-710; the radio needs **SCU-LAN10 = ON** (see
`docs/user/radio-setup.md`).

### Added

- Send any radio spectrum to N1MM Logger+ Spectrum Display as its external `<Spectrum>` UDP packet. (#1)
- Read the Yaesu FT-710 scope frames (span, scope mode, VFO, levels). (#2)
- Read the FT-710 scope over USB through FTDI's LibFT4222 (installed separately), with automatic resynchronisation. (#3)
- Record and replay scope captures; latest, average, and peak smoothing. (#4)
- Windows app: a one-folder build with `n1mm-scope-bridge.exe` and the windowed `N1MM Scope Bridge.exe`, licenses included. (#6)
- Multi-core streaming: reading, processing, and sending run on separate threads, one pipeline per radio. (#8)
- GPLv3 notices for code derived from wfview; `--license` shows the full terms. (#12)
- Full release regression for release candidates and releases. (#16)
- Settings saved for the GUI and usable from the command line with `run --settings`. (#17)
- Windows window (Qt) to configure and start/stop streaming, with inline checks, automatic saving, a built-in emulator option, and a modern look that follows light/dark mode. (#18)
- System tray: Close asks whether to keep streaming in the tray or exit (with Remember my choice), Minimize hides to the tray and keeps streaming, and the tray menu shows the window, starts/stops streaming, or exits. (#19)
- Windows installer: per-user install with Start menu and desktop shortcuts, optional start with Windows, and help getting FTDI's LibFT4222. (#20)
- Installer wizard screenshots (license, install folder, shortcuts and Start with Windows, FTDI LibFT4222, finish) are captured on Windows by the release regression and shown on the website's Install page. (#22)
- Website: full install, first-launch, N1MM+ setup, window, FAQ, and troubleshooting pages. The Troubleshooting page is generated from `docs/user/troubleshooting.md`, so the site always lists the messages the software can show. (#23)
- Command line: `run`, `record`, `probe`, and `list-radios`. (#25)
- Status panel (radio, VFO, span, scope mode, updates per second, errors), a log, and Copy diagnostics for bug reports. (#28)
- Optional UDP remote control (off by default, this PC only) and the `ctl` command, for N1MM+ macros and scripts. (#30)
- User guide for the command line, settings, and troubleshooting. (#31)
- Groundwork for the Qt (PySide6) GUI. (#33)
- Built-in FT-710 emulator (`--emulator`, `--scenario`) for trying the bridge without a radio. (#35)
- Tested against FTDI's real LibFT4222 and D2XX libraries in Windows CI (loading, function signatures, and the "radio not found" message). (#37)
- Code coverage reports on Codecov. (#39)
- Tag-triggered release workflow: RC pre-releases and final releases with the installer, app zip, wheel, sdist, SHA256SUMS, provenance attestations, and regression report; a workflow_dispatch dry run rehearses a release without publishing. (#46)
- The `gui` command opens the window from the command line (`n1mm-scope-bridge gui`). (#52)
- When the scope is not in Center mode, the bridge asks you once to switch it (for exact N1MM+ frequencies) and confirms when it is set. The bridge never changes the scope mode or opens the radio's COM ports. (#62)
- The website shows screenshots of the window, generated automatically from the program (`n1mm-scope-bridge gui --screenshot DIR`). (#68)
- Automation triage workflow that flags Copilot Autofix and Dependabot PRs, and unaddressed code-scanning alerts, for adoption. (#78)
- Copilot Autofix PRs are made compliant automatically: a tracking issue is created and linked, a changelog fragment is committed, and the PR checks are re-run. The Issue policy and Changelog checks now read the current PR, so edits made after a PR opens count. (#83)
- Golden-capture tooling for checking the FT-710 emulator against a real radio: `record --raw-stream`, `scripts/capture_golden.py` (works on Windows and macOS, with an emulator dry run), and a CI conformance test that waits for the captures. (#95)
- Merges are now blocked until every check passes and the pull request has no open CodeQL, secret-scanning, or dependency-review findings. (#97)
- GUI design system for the redesign: palette-based theme with WCAG AA status colours, Lucide icons, cards, a Settings dialog with pages, and a live spectrum and waterfall preview widget. (#101)
- Bench tooling for unattended FT-710 validation: `capture_golden.py --auto` sets the scope span and mode over a whitelisted CAT helper and restores them, and `hardware_smoke.py` streams the real radio through the bridge and checks the result. (#106)

### Changed

- Windows is the supported platform: Windows CI is required for every Python version; macOS runs a single portability job. (#15)
- README now describes the bridge for Yaesu radios in general (the FT-710 first, more models planned) and shows current status. (#70)
- Repository instructions for GitHub Copilot, and a documented policy for automated pull requests (Copilot Autofix, Dependabot). (#74)
- The GUI is now a dashboard: a live spectrum and waterfall preview of what N1MM+ receives, cards for frequency, span, scope mode, N1MM+ rate and health, a status pill with Start/Stop, Settings in a dialog with pages, and a collapsible Activity log, in light and dark. (#102)
- Documented the FT-710 radio setting the bridge needs (**OPERATION SETTING → GENERAL → SCU-LAN10 = ON**) in a new "Setting up your Yaesu radio" guide, the README, N1MM+ setup, the GUI guide, the emulator validation steps, and the website's Install and FAQ pages. (#114)
- Screenshots taken from the built-in FT-710 emulator are now labelled as simulated signals (not a real radio) on the website and in the docs. (#116)

### Fixed

- The GUI self-test no longer waits on the close prompt when a system tray is available. (#20)
- Recover cleanly from a misaligned or garbled scope stream instead of stalling. (#35)
- Resolved CodeQL alerts in the pipeline's stage error handling and the CLI's Ctrl-C handling, with no change in behaviour. (#69)
- Release notes now name the portable Windows zip by its real file name (`n1mm-scope-bridge-<version>-win64.zip`). (#87)
- The remote-control CLI test no longer fails on slow CI runners. (#108)
- Document that the FT-710 needs its SCU-LAN10 menu set to ON (no adapter needed) to send its scope over USB, and mention it in the "Could not open" error. (#109)
- Validated on a real FT-710: the bridge now decodes Cursor and Fixed scope modes (byte 32's high nibble is a mode flag; Fixed-mode edges come from the reported start frequency), and the emulator matches the radio's measured 11.2 frames/s, zero-filled frames with a 16-byte sync tail, and per-span noise floor. Golden captures from the radio are now checked in CI. (#111)

### Security

- Diagnostics now hide your Windows account name in folder paths. (#28)
- Remote control refuses to listen on all network interfaces (0.0.0.0 or ::); a LAN setup must name one specific interface IP plus an allow-list. (#100)

