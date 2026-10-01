# Command line

The GUI is the normal way to run the bridge. Everything it does can also be
done from a Command Prompt or PowerShell, which is useful for scripts,
headless station PCs, and troubleshooting.

```
n1mm-scope-bridge [--version] [--license] COMMAND [options]
```

| Global option | Meaning |
|---|---|
| `--version` | Print the version, copyright, and license notice |
| `--license` | Print the full license and warranty terms and where to get the source |
| `-h`, `--help` | Show help (also works after each command: `n1mm-scope-bridge run --help`) |

Exit codes: `0` success; `1` a problem you can fix (the message says what);
`2` invalid command-line usage.

## `run`: stream the scope to N1MM+

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
| `--settings [PATH]` | not used | Start from the GUI's saved settings (or from the settings file at `PATH`). Any option you also give on the command line wins. See [settings](settings.md). |
| `--host HOST` | `127.0.0.1` | The PC running N1MM+ (this PC by default) |
| `--port PORT` | `13064` | N1MM+'s spectrum UDP port |
| `--name TEXT` | radio model, for example `FT-710` | The source name you pick in N1MM+'s Spectrum Display settings |
| `--rate N` | `4` | Updates per second sent to N1MM+, more than 0 and at most 10 |
| `--scaling X` | `0.3125` | dB per level step, used by N1MM+ to draw the levels |
| `--combine MODE` | `latest` | How frames between updates are combined: `latest`, `average` (smoother), or `peak` (holds short signals) |
| `--ftdi-lib-dir DIR` | system search path | Folder containing FTDI's `LibFT4222-64.dll` and `ftd2xx.dll` |
| `--device TEXT` | `FT4222 A` | The FT4222 device description to open |
| `--replay FILE` | radio | Replay a capture file (see `record`) instead of reading the radio |
| `--loop` | off | With `--replay`, start again at the end of the file |
| `--fps N` | `20` | With `--replay`, frames per second to replay |
| `--duration SECONDS` | until Ctrl-C | Stop after this many seconds |

Examples:

```
n1mm-scope-bridge run
n1mm-scope-bridge run --settings
n1mm-scope-bridge run --host 192.168.1.20 --name "Shack FT-710" --combine peak
n1mm-scope-bridge run --replay my-ft710.cap --loop
```

## `record`: save raw scope frames

```
n1mm-scope-bridge record [--radio MODEL] [--frames N] [--ftdi-lib-dir DIR] [--device TEXT] OUT
```

| Option | Default | Meaning |
|---|---|---|
| `--frames N` | `50` | Number of frames to save (at least 1) |
| `OUT` | required | Capture file to write |
| `--radio`, `--ftdi-lib-dir`, `--device` | as for `run` | |

A short capture is the most useful thing to attach to a bug report or a
radio support request. Note what the radio's display showed at the time
(frequency, span, scope mode).

## `probe`: check the setup

```
n1mm-scope-bridge probe [--radio MODEL] [--ftdi-lib-dir DIR] [--device TEXT]
```

Loads the FTDI libraries, opens the radio, reads one frame, and prints the
VFO, span, and scope mode. Run this first if anything doesn't work.

```
FTDI libraries loaded.
FT-710 found on 'FT4222 A'.
VFO-A 14074000 Hz, span 20000 Hz, scope mode Center (Normal)
```

## `list-radios`

Prints the supported radio models and the `--radio` value for each.
