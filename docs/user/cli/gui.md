# `gui`

Opens the N1MM Scope Bridge window, the same as the **N1MM Scope Bridge**
shortcut or `n1mm-scope-bridge-gui`. See the [GUI guide](../gui.md).

```
n1mm-scope-bridge gui [--settings PATH] [--self-test]
                      [--screenshot DIR [--source emulator|radio] [--ftdi-lib-dir DIR] [--settle SECONDS]]
                      [--record DIR [--source emulator|radio|replay] [--replay CAPTURE] [--ftdi-lib-dir DIR] [--seconds N] [--fps N] [--format mp4|webm|gif ...]]
```

| Option | Default | Meaning |
|---|---|---|
| `--settings PATH` | the per-user settings file | Use a different settings file |
| `--self-test` | off | Open the window, stream the built-in emulator to a local test listener, and exit with code 0 on success |
| `--screenshot DIR` | off | Save PNG screenshots, light and dark, of the window (streaming and idle), Settings, and dialogs in a fixed demo state, plus `manifest.json` (sizes and alt text), into `DIR`, then exit. Used to build the website |
| `--record DIR` | off | Record the streaming window, light and dark, into `DIR` as H.264 MP4 and VP9 WebM videos at the source's own frame rate, a lighter GIF fallback, and a still PNG (for viewers who prefer reduced motion), and add a `manifest.json` entry, then exit. Used for the website's live recording. Needs Pillow and, for video, ffmpeg (on `PATH`, or the `imageio-ffmpeg` package) — development tools, never shipped |
| `--source SOURCE` | `emulator` | With `--screenshot` or `--record`: `emulator` uses the built-in FT-710 emulator (deterministic); `radio` reads the connected radio (receive only), and with `--screenshot` saves only the streaming window, labelled as a real-radio capture; `replay` (with `--record` only) plays back a capture recorded from a real radio with `record` |
| `--replay CAPTURE` | none | With `--source replay`: the capture file to play back, paced as live (11.2 frames per second, the FT-710's rate) |
| `--seconds N` | `15` | With `--record`: length of the recording |
| `--fps N` | source rate (about 11) | With `--record`: frames per second. The default records every radio frame, so the waterfall scrolls smoothly |
| `--format FORMAT` | `mp4`, `webm` and `gif` | With `--record`: output format; repeat for several. Each file is kept under 1 MiB (videos lower their quality, the GIF shrinks) |
| `--ftdi-lib-dir DIR` | system search path | With `--source radio`: folder containing FTDI's LibFT4222 and D2XX |
| `--settle SECONDS` | `20` | With `--source radio`: stream this long first so the waterfall fills with real signals |

The window needs the optional GUI package (PySide6). The Windows installer
includes it. With pip: `pip install "n1mm-scope-bridge[gui]"`.
