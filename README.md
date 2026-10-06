# n1mm-scope-bridge

**Website:** <https://reid-n0rc.github.io/n1mm-scope-bridge/>

[![CI](https://github.com/Reid-n0rc/n1mm-scope-bridge/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/Reid-n0rc/n1mm-scope-bridge/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/Reid-n0rc/n1mm-scope-bridge/branch/dev/graph/badge.svg)](https://codecov.io/gh/Reid-n0rc/n1mm-scope-bridge)

**Your Yaesu radio's waterfall, in N1MM Logger+.** n1mm-scope-bridge takes the
spectrum scope built into Yaesu radios and shows it in **N1MM Logger+'s
Spectrum Display window**. The **Yaesu FT-710** is the first supported model.
Other Yaesu models are planned (see [Supported radios](#supported-radios)).

> **Status: released ([latest release](https://github.com/Reid-n0rc/n1mm-scope-bridge/releases/latest)).**
> Validated on a real Yaesu FT-710: live scope streaming, all spans, and
> Center/Cursor/Fixed modes (the radio needs **SCU-LAN10 = ON**, then a power
> cycle and a USB replug; see [radio setup](docs/user/radio-setup.md)). One
> Windows installer covers x64, ARM64 and 32-bit PCs and handles FTDI's
> library and, optionally, its USB driver. Still to do: an on-air check with
> N1MM+ (#5), operator-only test captures (#36) and code signing (#130).
> See the **[website](https://reid-n0rc.github.io/n1mm-scope-bridge/)** and
> the **[user guide](docs/user/README.md)**.

## Getting started

1. **Set up the radio:** on the FT-710 set **OPERATION SETTING → GENERAL →
   SCU-LAN10** to **ON** (no adapter needed), turn the radio off and on, then
   unplug and replug the USB cable. Put the scope in **Center** mode.
2. **Install:** download `n1mm-scope-bridge-setup-<version>.exe` from the
   [latest release](https://github.com/Reid-n0rc/n1mm-scope-bridge/releases/latest)
   and run it (Windows 10/11; it fetches FTDI's library for you).
3. **Start the bridge** and press **Start**.
4. **In N1MM+:** **Window → Spectrum Display** → gear → **For all other
   radios, source named** → pick `FT-710`. See N1MM+'s
   [Spectrum Display Window](https://n1mmwp.hamdocs.com/manual-windows/spectrum-display-window/)
   documentation.

The full step-by-step guide, with every required radio setting and links to
N1MM+'s documentation, is **[Getting started](docs/user/getting-started.md)**
(also on the [website](https://reid-n0rc.github.io/n1mm-scope-bridge/getting-started.html)).

## Test coverage

[![Codecov coverage tree graph](https://codecov.io/gh/Reid-n0rc/n1mm-scope-bridge/graphs/tree.svg?token=X0SYOVMX1M)](https://app.codecov.io/gh/Reid-n0rc/n1mm-scope-bridge)

## Disclaimer

N1MM Scope Bridge is an independent open-source project. It is not affiliated with, endorsed by, or supported by the N1MM Logger+ project, its developers, or N1MM. It uses N1MM Logger+'s publicly documented external UDP interface. N1MM Logger+ is the work of its own authors. Yaesu and FT-710 are trademarks of Yaesu Musen Co., Ltd.; this project is not affiliated with Yaesu, FTDI, or the wfview project. Other names are trademarks of their respective owners.

See [docs/legal-notices.md](docs/legal-notices.md).

## Why

N1MM+ draws a native spectrum/waterfall for Icom radios that send scope data
over CI-V, and for Flex and some SDRs. It has no native support for the scope
in Yaesu's current radios, even though they produce it. This project reads
the radio's scope stream and forwards it to N1MM+ through N1MM's documented
external spectrum interface.

## How it works

The bridge has two sides. A per-model **radio side** reads the scope, and a
shared **N1MM side** sends it to N1MM+.

- **N1MM side (all radios).** N1MM+ accepts spectrum data from external
  programs as a UTF-8 `<Spectrum>` XML datagram on UDP port 13064. Each
  datagram has a source name, the low and high frequencies in kHz, a dB
  scaling factor, and comma-separated levels. See
  [docs/n1mm-spectrum-protocol.md](docs/n1mm-spectrum-protocol.md).
- **No CAT conflict.** The bridge never opens the radio's CAT COM port. The
  frequency and span come from the scope data itself, so N1MM+ keeps exclusive
  control of the radio.
- **Multi-core.** Each radio runs as its own reader → process → sender
  thread pipeline, and the reader is never blocked by the stages after it. On
  free-threaded Python (3.14t) all stages run in parallel on separate cores.
- **No radio needed for testing.** A built-in emulator
  ([docs/emulator.md](docs/emulator.md)) stands in for the radio in every
  automated test, and for demos (`n1mm-scope-bridge run --emulator`).

### Yaesu FT-710

```
 FT-710 USB ──┬── CP210x COM ports (CAT) ─────────────► N1MM+ (radio control, unchanged)
              │
              └── FTDI FT4222 "FT4222 A" (SPI) ──► n1mm-scope-bridge ──UDP :13064──► N1MM+ Spectrum Display
                     4096-byte frames, ~850 bins           <Spectrum> XML
```

The FT-710's USB port has an FTDI FT4222 USB-to-SPI bridge next to the usual
CAT COM ports. The radio streams 4096-byte frames through it. Each frame holds
an 850-point spectrum line, the VFO frequencies, the scope span, and the scope
mode. This was reverse-engineered by the
[wfview](https://gitlab.com/eliggett/wfview) project (W6EL and M0VSE). See
[docs/protocol-yaesu-ft4222.md](docs/protocol-yaesu-ft4222.md). Put the
FT-710's scope in **Center** mode for exact frequencies in N1MM+.

**Required radio setting:** the FT-710 only exposes its FT4222 scope interface
over USB when the menu item **OPERATION SETTING → GENERAL → SCU-LAN10** is
**ON**. You don't need the SCU-LAN10 adapter; the setting alone turns on the
scope output (wfview documents the same requirement). If it is OFF, the
radio's USB connection shows only the COM ports and audio, and the bridge
reports `Could not open 'FT4222 A'`.

More detail: [docs/architecture.md](docs/architecture.md).

## Supported radios

| Radio | Transport | Status |
|-------|-----------|--------|
| Yaesu FT-710 | USB, FT4222 SPI | Supported (validated on a real radio; N1MM+ on-air check pending, #5) |
| Yaesu FTDX10 | USB, FT4222 SPI (believed same as FT-710) | Planned, needs an owner to verify (#7) |
| Yaesu FTDX101D/MP | USB, FT4222 SPI (expected dual-receiver frames) | Planned, needs an owner to verify (#7) |
| Yaesu radios on SCU-LAN10 | Network (wfview's Yaesu LAN protocol) | Planned (#7) |
| Icom (IC-7300, IC-7610, IC-705, …) | Not needed | N1MM+ supports these natively |

Own one of the planned radios? Open a **Radio support request** issue. To add
a radio, see [docs/adding-a-radio.md](docs/adding-a-radio.md).

## Install (Windows)

Follow **[Getting started](docs/user/getting-started.md)**; it covers the
radio settings, the installer and N1MM+ in order. In short:

- **One installer for all Windows PCs**, from the
  [latest release](https://github.com/Reid-n0rc/n1mm-scope-bridge/releases/latest)
  (the only file on each release; the notes give its SHA-256). 64-bit
  Intel/AMD Windows gets the full app. Windows on ARM gets the x64 app by
  default, or optionally a native ARM64 build, for which you add FTDI's ARM64
  DLLs yourself. 32-bit Windows gets the command-line version (**N1MM Scope
  Bridge (command line)** in the Start menu). Details:
  [install page](https://reid-n0rc.github.io/n1mm-scope-bridge/install.html).
- It installs for your Windows account only (no admin prompt). **FTDI
  LibFT4222** is downloaded by setup from a pinned, checksum- and
  signature-verified source, because we can't ship FTDI's library inside our
  GPL installer. Setup can also install FTDI's USB driver (needs
  administrator) if Windows doesn't have it. Without internet, see
  [radio setup](docs/user/radio-setup.md).
- The installer isn't code-signed yet (#130), so SmartScreen may warn:
  **More info → Run anyway**.
- N1MM+ setup: [docs/n1mm-setup.md](docs/n1mm-setup.md).

macOS and Linux: the code is portable and tested there in CI, but these
platforms are unsupported for operators. To run from source on any platform,
see Development below and install with the `gui` extra.

## Roadmap

Work is tracked as GitHub issues, each small enough for one focused change
(see [AGENTS.md](AGENTS.md), Task sizing).

**Done:** N1MM `<Spectrum>` sender, FT-710 frame parser and FT4222 reader
(validated on a real FT-710 and tested against FTDI's real DLLs on x64, ARM64
and x86 in CI), multi-core pipeline, command line, settings, Windows GUI
(system tray, close prompt, live status, preview off by default,
Center-mode helper, remote control), optional UDP remote control, FT-710
emulator with golden captures from the real radio, one universal Windows
installer with FTDI library download and optional driver install, release
regression suite, user docs, and the website.

**Next:**

1. On-air check with N1MM+ (#5) and the operator-only test captures (#36)
2. Code signing for the installer (#130)
3. Verify Cursor-mode frequency edges (currently unverified)
4. More Yaesu radios (#7)

## Command line (advanced)

The GUI (`n1mm-scope-bridge-gui`, see the [GUI guide](docs/user/gui.md)) is the
normal way to run the bridge. The same features
are available from a terminal:

```
n1mm-scope-bridge probe                 # check the FTDI library and the radio
n1mm-scope-bridge run                   # stream the radio's scope to N1MM+ on this PC
n1mm-scope-bridge run --emulator        # no radio: try it, or test your N1MM+ setup
n1mm-scope-bridge run --host 192.168.1.20 --name "Shack FT-710" --combine peak
n1mm-scope-bridge record --frames 50 my-ft710.cap
n1mm-scope-bridge run --replay my-ft710.cap --loop   # test without the radio
```

Run `n1mm-scope-bridge COMMAND --help` for all options. The full reference is in
the [user guide](docs/user/README.md): [command line](docs/user/cli.md),
[settings](docs/user/settings.md), and [troubleshooting](docs/user/troubleshooting.md).

## Development

```bash
uv sync                          # create .venv with dev tools
git config core.hooksPath .githooks
uv run pytest --cov              # unit tests (no radio needed)
uv run ruff check . && uv run ruff format --check . && uv run mypy
sh tests/hooks/run.sh            # git hook tests
```

Building the Windows app: [docs/building-windows.md](docs/building-windows.md).

Read [AGENTS.md](AGENTS.md) before contributing. Humans and AI agents follow
the same rules. See also [CONTRIBUTING.md](CONTRIBUTING.md).

## Code signing and privacy

- [Code signing policy](docs/code-signing-policy.md): team roles, what is signed, and how to verify a release.
- [Privacy statement](docs/privacy.md): the program collects no personal data.

## Credits and license

The Yaesu FT4222 scope protocol knowledge, and the code ported from it, come from
[wfview](https://gitlab.com/eliggett/wfview), copyright 2017–2026 Elliott H.
Liggett (W6EL) and Phil E. Taylor (M0VSE), licensed under GPLv3. Thank you to
the wfview team. The N1MM+ spectrum interface is documented by the N1MM
Logger+ team.

This project is licensed under **GPL-3.0-only** ([LICENSE](LICENSE)), so it
stays compatible with wfview's license. Third-party material is listed in
[THIRD_PARTY.md](THIRD_PARTY.md).

73 de N0RC
