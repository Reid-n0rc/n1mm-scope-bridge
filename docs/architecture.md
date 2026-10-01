# Architecture

```
┌──────────────────┐   bytes   ┌──────────────────┐ SpectrumFrame ┌──────────┐ SpectrumFrame ┌──────────────┐  UDP
│ Transport        │──────────►│ Frame parser     │──────────────►│ Bridge   │──────────────►│ N1MM sender  │──────► N1MM+
│ (FT4222 / file)  │           │ (pure, per radio)│               │ (rate,   │               │ (XML encode) │ :13064
└──────────────────┘           └──────────────────┘               │  average)│               └──────────────┘
                                                                  └──────────┘
```

## Modules (planned, `src/n1mm_scope_bridge/`)

| Module | Responsibility | I/O? |
|--------|----------------|------|
| `spectrum.py` | `SpectrumFrame` dataclass: `low_hz`, `high_hz`, `levels` (sequence of ints), `max_level`, `source_status` | No |
| `n1mm.py` | `encode_spectrum(frame, name, scaling, app) -> bytes`, plus `N1mmSender` (UDP socket wrapper) | Sender only |
| `radios/base.py` | `RadioProfile` (model, transport, spans, frame size) and the `SpectrumSource` protocol (`frames() -> Iterator[SpectrumFrame]`, `close()`) | No |
| `radios/yaesu_scope.py` | Pure parser: 4096-byte FT4222 frame → `YaesuScopeStatus` + `SpectrumFrame` | No |
| `radios/ft710.py` | FT-710 profile (span table, scope modes) | No |
| `transport/ft4222.py` | `ctypes` binding to LibFT4222/D2XX, SPI setup, 4096-byte reads, resync | Yes |
| `transport/replay.py` | Read and write raw-frame capture files, for `--record` and `--replay` | Yes |
| `bridge.py` | Main loop: pull frames, throttle to the N1MM rate, optionally average or peak-hold, send | No (injected) |
| `cli.py` | `run`, `record`, `list-radios`, and `probe` commands | Wires I/O |

## Principles

- **Pure core, thin I/O.** Parsing, encoding, and throttling are pure and
  fully unit-tested. Device, socket, and file access sit behind small
  interfaces that tests replace with fakes.
- **Read-only toward the radio.** The bridge never sends CAT commands and
  never opens the CAT port. Everything it needs comes from the scope frame.
- **One radio, one module.** Model-specific details live in that radio's
  profile and parser. Shared Yaesu FT4222 logic is reused across models.
- **Record and replay.** `record` writes raw frames to a capture file, and
  `run --replay` feeds a capture through the same pipeline. This lets anyone
  debug or add a radio without having the radio, using a capture someone else
  provided.

## Capture file format (planned)

A capture is a header line followed by raw frames:
`N1MMSB1 <radio-model> <frame-size>\n` + N × `<frame-size>` bytes. Fixtures
committed under `tests/fixtures/` must stay under 1 MiB (the pre-commit hook
enforces this). In practice that means a few frames.
