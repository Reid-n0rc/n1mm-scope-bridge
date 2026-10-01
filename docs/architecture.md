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
| `demo.py` | Deterministic synthetic FT-710 frames (demo mode, screenshots, test fixture) | No |
| `pipeline.py` | Threaded reader → process → sender stages, drop-oldest queue, per-radio pipelines (`MultiPipeline`) | No (injected) |
| `bridge.py` | Wires a radio's transport, parser, combiner (latest/average/peak) and N1MM sender into a `Pipeline` | No (injected) |
| `cli.py` | `run`, `record`, `list-radios`, and `probe` commands | Wires I/O |

## Concurrency (multi-core)

```
per radio:  reader thread ──LatestQueue──► process thread ──Accumulator──► sender thread ──UDP──► N1MM+
            (ctypes read,    (drop-oldest,   (parse +        (lock-protected  (fixed tick,
             GIL released)    never blocks)   combine)         latest/avg/peak)  4 Hz default)
```

- **Three threads per radio.** The reader only moves bytes. FT4222 reads are
  `ctypes` calls, which release the GIL, so USB I/O overlaps parsing even on
  standard CPython.
- **Never block the reader.** `LatestQueue` drops the oldest frame when full
  and counts the drops. A stale spectrum line is worthless.
- **One pipeline per radio** (`MultiPipeline`, for SO2R). Pipelines share no
  mutable state, so radios scale across cores. If one pipeline fails, all of
  them stop.
- **Free-threaded Python.** CI runs the suite on CPython 3.14t (no GIL),
  where all stages run in parallel on separate cores. Frames are immutable
  (frozen dataclasses, tuples, and bytes) so this is safe without extra
  locking.
- **Shutdown.** `stop()` sets one event and closes the source to unblock the
  reader. All threads are non-daemon and joined. A stage exception stops the
  pipeline and is re-raised from `join()`.
- **No multiprocessing.** Pickling 4 KiB frames 50 times per second costs more
  than the work itself. Revisit only if hardware profiling (#5) shows a
  CPU-bound stage.

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
