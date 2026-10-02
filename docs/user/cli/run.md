# `run`: stream the scope to N1MM+

```
n1mm-scope-bridge run [options]
```

Streams the radio's spectrum scope to N1MM+ until you press **Ctrl-C** (or
until `--duration` ends). A status line is printed once per second:

```
VFO 14.074000 MHz, span 20 kHz, Center (Normal) | read 412 | sent 40 | dropped 0 | bad 0
```

| Option | Default | Meaning |
|---|---|---|
| `--radio MODEL` | `ft710` | Radio model (see `list-radios`) |
| `--settings [PATH]` | not used | Start from the GUI's saved settings (or from the settings file at `PATH`). Any option you also give on the command line wins. See [settings](../settings.md). |
| `--host HOST` | `127.0.0.1` | The PC running N1MM+ (this PC by default) |
| `--port PORT` | `13064` | N1MM+'s spectrum UDP port |
| `--name TEXT` | radio model, for example `FT-710` | The source name you pick in N1MM+'s Spectrum Display settings |
| `--rate N` | `4` | Updates per second sent to N1MM+, more than 0 and at most 10 |
| `--scaling X` | `0.3125` | dB per level step, used by N1MM+ to draw the levels |
| `--combine MODE` | `latest` | How frames between updates are combined: `latest`, `average` (smoother), or `peak` (holds short signals) |
| `--ftdi-lib-dir DIR` | system search path | Folder containing FTDI's `LibFT4222-64.dll` and `ftd2xx.dll` |
| `--device TEXT` | `FT4222 A` | The FT4222 device description to open |
| `--emulator` | off | Use the built-in FT-710 emulator instead of a radio: for trying the bridge, demos, and N1MM+ setup without the radio connected |
| `--scenario NAME` | `steady` | Emulator scenario (implies `--emulator`): `steady`, `band-scan`, `span-steps`, `mode-change`, `tx-burst`, `misaligned-start`, `corrupt-frames`, `usb-unplug`, `silent-radio`, `not-connected` |
| `--replay FILE` | radio | Replay a capture file (see `record`) instead of reading the radio |
| `--loop` | off | With `--replay`, start again at the end of the file |
| `--fps N` | `20` | With `--replay`, frames per second to replay |
| `--duration SECONDS` | until Ctrl-C | Stop after this many seconds |
| `--control-port PORT` | off | Turn on [UDP remote control](../udp-control.md) on this port (normally `13070`), listening on this PC only |

Examples:

```
n1mm-scope-bridge run
n1mm-scope-bridge run --settings
n1mm-scope-bridge run --host 192.168.1.20 --name "Shack FT-710" --combine peak
n1mm-scope-bridge run --replay my-ft710.cap --loop
n1mm-scope-bridge run --emulator          # no radio: test your N1MM+ setup
```
