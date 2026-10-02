# `record`: save raw scope frames

```
n1mm-scope-bridge record [--radio MODEL] [--frames N] [--raw-stream] [--ftdi-lib-dir DIR] [--device TEXT] OUT
```

| Option | Default | Meaning |
|---|---|---|
| `--frames N` | `50` | Number of frames to save (at least 1) |
| `--raw-stream` | off | Save every read from the radio's USB scope interface exactly as received, with timing, before frames are lined up. Used to check the emulator against a real radio ([emulator.md](../../emulator.md)); normal captures don't need it |
| `OUT` | required | Capture file to write |
| `--radio`, `--ftdi-lib-dir`, `--device`, `--emulator`, `--scenario` | as for [`run`](run.md) | |

A short capture is the most useful thing to attach to a bug report or a
radio support request. Note what the radio's display showed at the time
(frequency, span, scope mode).
