# Settings

The GUI saves your settings automatically. The command line uses them when
you pass `run --settings`.

**Location**

| Windows | `%APPDATA%\n1mm-scope-bridge\settings.json` |
|---|---|
| macOS (unsupported) | `~/Library/Application Support/n1mm-scope-bridge/settings.json` |
| Linux (unsupported) | `$XDG_CONFIG_HOME/n1mm-scope-bridge/settings.json` (or `~/.config/…`) |

The file is plain JSON. If it is damaged, the program renames it to
`settings.json.bak`, starts with defaults, and tells you. Unknown entries
are ignored, and an entry with the wrong type falls back to its default with
a warning.

| Setting | Default | Command-line option | Meaning |
|---|---|---|---|
| `radio` | `ft710` | `--radio` | Radio model |
| `source_name` | empty (the radio model) | `--name` | Source name shown in N1MM+ |
| `n1mm_host` | `127.0.0.1` | `--host` | PC running N1MM+ |
| `n1mm_port` | `13064` | `--port` | N1MM+ spectrum UDP port |
| `rate_hz` | `4.0` | `--rate` | Updates per second to N1MM+ (at most 10) |
| `scaling` | `0.3125` | `--scaling` | dB per level step |
| `combine` | `latest` | `--combine` | `latest`, `average`, or `peak` |
| `ftdi_lib_dir` | empty (system path) | `--ftdi-lib-dir` | Folder with FTDI's LibFT4222 and ftd2xx DLLs |
| `device` | `FT4222 A` | `--device` | FT4222 device description |
| `emulator` | `false` | `--emulator` | Use the built-in FT-710 emulator instead of the radio, to try the bridge or set up N1MM+ without the radio. The GUI saves it; the command line uses `--emulator` |
| `start_streaming_on_launch` | `false` | — | GUI: start streaming as soon as it opens |
| `start_minimized` | `false` | — | GUI: start hidden in the system tray |
| `on_close` | `ask` | — | GUI Close button: `ask`, `tray` (keep streaming in the tray), or `exit` |

Each setting is checked before use, and a problem is reported by name, for
example `n1mm_port: port must be 1-65535 (N1MM+ uses 13064)`.
