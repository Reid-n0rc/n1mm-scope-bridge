# `record`: save raw scope frames

```
n1mm-scope-bridge record [--radio MODEL] [--frames N] [--ftdi-lib-dir DIR] [--device TEXT] OUT
```

| Option | Default | Meaning |
|---|---|---|
| `--frames N` | `50` | Number of frames to save (at least 1) |
| `OUT` | required | Capture file to write |
| `--radio`, `--ftdi-lib-dir`, `--device`, `--emulator`, `--scenario` | as for [`run`](run.md) | |

A short capture is the most useful thing to attach to a bug report or a
radio support request. Note what the radio's display showed at the time
(frequency, span, scope mode).
