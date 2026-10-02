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
| `force_center_mode` | `false` | `run --force-center-mode` | Switch the radio's scope to **Center** while streaming (exact N1MM+ frequencies) and restore your previous scope mode afterwards. **Off by default.** Works with the emulator today; with a real FT-710 it needs a CAT path still being tested (#62). See [GUI](gui.md) and [troubleshooting](troubleshooting.md) |
| `control_enabled` | `false` | `run --control-port` | Optional [UDP remote control](udp-control.md). **Off by default.** |
| `control_port` | `13070` | `run --control-port` | Remote-control UDP port (must differ from the N1MM+ port) |
| `control_bind` | `127.0.0.1` | — | Address the remote-control listener uses. Leave it on `127.0.0.1` (this PC only) unless you need control from another PC |
| `control_allow` | empty | — | Client IPs allowed to send commands, separated by commas. Required if `control_bind` is not a loopback address |

Each setting is checked before use, and a problem is reported by name, for
example `n1mm_port: port must be 1-65535 (N1MM+ uses 13064)`.
