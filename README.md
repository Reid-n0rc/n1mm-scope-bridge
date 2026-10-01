# n1mm-scope-bridge

Show your radio's panadapter/waterfall in **N1MM Logger+'s Spectrum Display
window**. The first target is the **Yaesu FT-710**. The design is pluggable so
other radios can follow.

> **Status: pre-alpha.** The repository, process, and design are in place. The
> bridge itself is being built in small, separately reviewed issues. See the
> [roadmap](#roadmap). It does not do anything useful yet.

## Why

N1MM+ draws a native spectrum/waterfall for Icom radios that send scope data
over CI-V, and for Flex and some SDRs. It has no native support for the Yaesu
FT-710's scope, even though the FT-710 streams that scope over USB. This
project reads the FT-710's scope stream and forwards it to N1MM+ through
N1MM's documented external spectrum interface.

## How it works

```
 FT-710 USB ──┬── CP210x COM ports (CAT) ─────────────► N1MM+ (radio control, unchanged)
              │
              └── FTDI FT4222 "FT4222 A" (SPI) ──► n1mm-scope-bridge ──UDP :13064──► N1MM+ Spectrum Display
                     4096-byte frames, ~850 bins           <Spectrum> XML
```

- **Radio side.** The FT-710's USB port has an FTDI FT4222 USB-to-SPI bridge
  next to the usual CAT COM ports. The radio streams 4096-byte frames through
  it. Each frame holds an 850-point spectrum line, the VFO frequencies, the
  scope span, and the scope mode. This was reverse-engineered by the
  [wfview](https://gitlab.com/eliggett/wfview) project (W6EL and M0VSE). See
  [docs/protocol-yaesu-ft4222.md](docs/protocol-yaesu-ft4222.md).
- **N1MM side.** N1MM+ accepts spectrum data from external programs as a UTF-8
  `<Spectrum>` XML datagram on UDP port 13064. Each datagram has a source name,
  the low and high frequencies in kHz, a dB scaling factor, and
  comma-separated levels. See [docs/n1mm-spectrum-protocol.md](docs/n1mm-spectrum-protocol.md).
- **No CAT conflict.** The bridge never opens the CAT COM port. The frequency
  and span come from the scope frame itself, so N1MM+ keeps exclusive control
  of the radio.

- **Multi-core.** Each radio runs as its own reader → process → sender
  thread pipeline, and the reader is never blocked by the stages after it. On
  free-threaded Python (3.14t) all stages run in parallel on separate cores.

More detail: [docs/architecture.md](docs/architecture.md).

## Supported radios

| Radio | Transport | Status |
|-------|-----------|--------|
| Yaesu FT-710 | USB, FT4222 SPI | In development (primary target) |
| Yaesu FTDX10 | USB, FT4222 SPI (believed same as FT-710) | Planned, needs an owner to verify |
| Yaesu FTDX101D/MP | USB, FT4222 SPI (expected dual-receiver frames) | Planned, needs an owner to verify |
| Yaesu radios on SCU-LAN10 | Network (wfview's Yaesu LAN protocol) | Planned |
| Icom (IC-7300, IC-7610, IC-705, …) | Not needed | N1MM+ supports these natively |

To request a radio, open a **Radio support request** issue. To add one, see
[docs/adding-a-radio.md](docs/adding-a-radio.md).

## Requirements (planned)

- Windows 10/11, where N1MM+ runs. Development and the unit tests also run on
  Linux and macOS.
- Python 3.10 or later. A standalone Windows build is on the roadmap.
- FTDI's **LibFT4222** and **D2XX** libraries, installed from
  [ftdichip.com](https://ftdichip.com/products/ft4222h/). This repository does
  not ship them.
- N1MM Logger+ with the Spectrum Display window set to read an external
  source by name. See [docs/n1mm-setup.md](docs/n1mm-setup.md).

## Roadmap

Work is tracked as GitHub issues. Each issue is small enough for one focused
change (see [AGENTS.md](AGENTS.md), Task sizing).

1. N1MM `<Spectrum>` packet encoder and UDP sender
2. FT-710 scope frame parser (pure function, fixture-driven tests)
3. LibFT4222 ctypes reader with frame resync
4. Multi-core threaded pipeline (one pipeline per radio)
5. Bridge loop, CLI, and record/replay of raw frames
6. Hardware validation on an FT-710: span, scope modes, and dB scaling
7. Windows standalone build and release packaging
8. More radios (FTDX10, FTDX101, SCU-LAN10)

## Command line (advanced)

The GUI is the normal way to run the bridge (coming soon). The same features
are available from a terminal:

```
n1mm-scope-bridge probe                 # check the FTDI library and the radio
n1mm-scope-bridge run                   # stream the FT-710 scope to N1MM+ on this PC
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

Read [AGENTS.md](AGENTS.md) before contributing. Humans and AI agents follow
the same rules. See also [CONTRIBUTING.md](CONTRIBUTING.md).

## Credits and license

The FT-710 scope protocol knowledge, and the code ported from it, come from
[wfview](https://gitlab.com/eliggett/wfview), copyright 2017–2026 Elliott H.
Liggett (W6EL) and Phil E. Taylor (M0VSE), licensed under GPLv3. Thank you to
the wfview team. The N1MM+ spectrum interface is documented by the N1MM
Logger+ team.

This project is licensed under **GPL-3.0-only** ([LICENSE](LICENSE)), so it
stays compatible with wfview's license. Third-party material is listed in
[THIRD_PARTY.md](THIRD_PARTY.md).

73 de N0RC
