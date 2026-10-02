# `gui`

Opens the N1MM Scope Bridge window, the same as the **N1MM Scope Bridge**
shortcut or `n1mm-scope-bridge-gui`. See the [GUI guide](../gui.md).

```
n1mm-scope-bridge gui [--settings PATH] [--self-test] [--screenshot DIR [--source emulator|radio] [--ftdi-lib-dir DIR] [--settle SECONDS]]
```

| Option | Default | Meaning |
|---|---|---|
| `--settings PATH` | the per-user settings file | Use a different settings file |
| `--self-test` | off | Open the window, stream the built-in emulator to a local test listener, and exit with code 0 on success |
| `--screenshot DIR` | off | Save PNG screenshots, light and dark, of the window (streaming and idle), Settings, and dialogs in a fixed demo state, plus `manifest.json` (sizes and alt text), into `DIR`, then exit. Used to build the website |
| `--source SOURCE` | `emulator` | With `--screenshot`: `emulator` uses the built-in FT-710 emulator (every scene, deterministic); `radio` reads the connected radio (receive only) and saves only the streaming window, labelled as a real-radio capture |
| `--ftdi-lib-dir DIR` | system search path | With `--source radio`: folder containing FTDI's LibFT4222 and D2XX |
| `--settle SECONDS` | `20` | With `--source radio`: stream this long first so the waterfall fills with real signals |

The window needs the optional GUI package (PySide6). The Windows installer
includes it. With pip: `pip install "n1mm-scope-bridge[gui]"`.
