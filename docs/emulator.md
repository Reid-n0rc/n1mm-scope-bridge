# FT-710 emulator

Automated tests never need a radio. `n1mm_scope_bridge.emulator` provides a
software FT-710 behind the same `Ft4222Api` interface as FTDI's real
library, so the reader, resync, parser, pipeline, CLI, and GUI all run
unmodified against it. wfview has no automated tests or rig emulator, so this
is new ground.

## Using it

```
n1mm-scope-bridge run --emulator                 # demo or N1MM+ setup without the radio
n1mm-scope-bridge run --scenario band-scan       # implies --emulator
n1mm-scope-bridge probe --scenario not-connected # see the error an operator would see
```

From Python:

```python
from n1mm_scope_bridge.emulator import Ft710Emulator, Faults, make_emulator

emu = make_emulator("misaligned-start", fps=0)  # fps=0: as fast as possible (tests)
emu.tune(7_074_000)
emu.set_span(6)
emu.set_tx(True)
```

## Scenarios

| Name | What it does | Expected bridge behaviour |
|---|---|---|
| `steady` | 20 m FT8 segment, Center mode | streams |
| `band-scan` | tunes 14.000 → 14.350 MHz | streams; edges follow the VFO |
| `span-steps` | all 10 spans | streams; edges follow the span |
| `mode-change` | Center → Cursor → Fixed | streams; warns outside Center mode |
| `tx-burst` | transmits 20 of every 60 frames | streams; own signal visible |
| `misaligned-start` | stream starts mid-frame | resyncs, then streams |
| `corrupt-frames` | every 25th frame loses sync | resyncs, then keeps streaming |
| `usb-unplug` | I/O error after 20 frames | stops with `FT4222_SPIMaster_SingleRead failed` |
| `silent-radio` | opens, never sends data | stops with `No valid scope frames` |
| `not-connected` | device not found | stops with `Could not open` |

Every scenario runs in CI (`tests/test_emulator.py`) and through the real CLI
in the release regression ("Emulator scenarios through the CLI").

## How it is kept honest

The emulator implements wfview's protocol notes, checked against a real
FT-710 (#111): frames are zero-filled and end with the sync pattern four times
(`padding="tail"`, the default; `"sync"` and `"zero"` remain for resync tests),
the radio streams 11.2 frames per second, byte 32 carries a Cursor/Fixed flag
in its high nibble, byte 144 is the Fixed-mode start frequency, and the noise
floor per span uses measured values. Still marked `UNVERIFIED`: Cursor-mode
edges, transmit flags, and the start-up and re-plug behaviour (operator-only
cases).

Issue #36 records golden captures from a real FT-710 once and checks the
emulator against them in CI on every PR
(`tests/test_emulator_conformance.py`). Until the captures are committed,
those tests are expected failures marked "awaiting golden capture (#36)".
After that, the emulator is a checked stand-in for the radio. Changing the
parser (`radios/yaesu_scope.py`) or updating the radio firmware means
recapturing; the conformance test fails if the parser changed since the
captures were taken.

The emulator paces frames against a deadline, so it streams at exactly its
configured rate (11.2 frames/s, `EMULATOR_FPS`, measured on a real FT-710) however long a frame takes to
build. That is what the radio's measured rate is compared against.

## Validating against your radio

Do this once per radio firmware version, at the radio, on Windows or macOS.
It takes about 20 minutes. The tool only **reads** the scope stream. It never
transmits and never changes radio settings. For the transmit case you key the
radio yourself into a dummy load.

1. Close everything that uses the radio's USB scope interface: N1MM+, wfview,
   flrig, and any running `n1mm-scope-bridge`.
2. Install FTDI's LibFT4222 (<https://ftdichip.com/products/ft4222h/>):
   - **Windows:** the folder with `LibFT4222-64.dll` and `ftd2xx.dll`
   - **macOS:** the folder with `libft4222.dylib` (and `libftd2xx.dylib` if
     FTDI ships it separately)
3. Rehearse with the emulator (no radio needed):

   ```
   uv run python scripts/capture_golden.py --dry-run --yes
   ```

4. Check the radio is visible:

   ```
   uv run n1mm-scope-bridge probe --ftdi-lib-dir <FTDI folder>
   ```

5. Record the golden captures and follow the prompts. For each case, set the
   radio as shown, press Enter, and confirm what the radio displayed (or type
   a note). Type `s` to skip a case.

   ```
   uv run python scripts/capture_golden.py --ftdi-lib-dir <FTDI folder>
   ```

   The cases are: Center mode at all 10 spans, Cursor mode, Fixed mode,
   transmit into a dummy load, power-on start-up, and USB re-plug. Use
   `--only <case> ...` to redo some of them.
6. Run `uv run pytest tests/test_emulator_conformance.py`. Any difference
   between the radio and the emulator is listed by name, for example
   `real frames use 'zero' padding, emulator uses 'sync'`.
7. Commit `tests/fixtures/golden/` (the `.raw` files and `manifest.json`) in a
   PR for #36. Fix any conformance differences in the emulator in the same PR,
   or in a linked one. Then remove the `UNVERIFIED (#36)` notes the captures
   settle.

Raw captures are also handy for bug reports: `n1mm-scope-bridge record
--raw-stream --frames 50 my-radio.raw` keeps exactly what the radio sent,
before frames are lined up.

## Native boundary: FTDI's real libraries

The emulator replaces FTDI's library at the Python level. The real native
boundary is tested against **FTDI's own DLLs** in Windows CI:

- `scripts/fetch_ftdi.py` fetches FTDI's signed LibFT4222 1.4.8 (the
  version wfview builds against) and `ftd2xx.dll`. They come from the PyPI
  `ft4222` wheel, because ftdichip.com blocks automated downloads. The wheel's
  SHA-256 is pinned, both Authenticode signatures are checked on Windows, the
  download is cached, and the DLLs are never committed or shipped.
- `tests/test_native_ftdi.py` (`native` marker, skipped unless
  `N1MM_BRIDGE_FTDI_DIR` is set) checks DLL loading (including the
  `ftd2xx.dll` dependency through `os.add_dll_directory`), symbol resolution,
  ctypes signatures and the stdcall convention, `FT_OpenEx` returning
  `FT_DEVICE_NOT_FOUND`, and `probe` printing the friendly "Could not open"
  error.
- The release regression repeats the `probe` check on Windows.

CI runners have no FT-710 attached, so **streaming data is covered by the
emulator**, not the real DLLs. It is validated against the real radio once
through golden captures (#36).

### Unattended validation (bench tooling)

With N1MM+, flrig and wfview closed, the FT-710 on USB, and FTDI's LibFT4222
in a local folder (never committed):

```
uv sync --group hardware
uv run n1mm-scope-bridge probe --ftdi-lib-dir <ftdi folder>
uv run python scripts/hardware_smoke.py --ftdi-lib-dir <ftdi folder> \
    --cat-port <CAT/Enhanced port> --minutes 5 --report hardware-smoke.md
uv run python scripts/capture_golden.py --auto --cat-port <CAT/Enhanced port> \
    --ftdi-lib-dir <ftdi folder> --firmware <radio firmware>
uv run pytest tests/test_emulator_conformance.py
```

- `hardware_smoke.py` streams the real radio through the bridge into a local
  UDP listener and checks packets, frame rate, errors and resyncs. With
  `--cat-port` it also compares the VFO-A reading over CAT (read-only `FA;`)
  with the scope stream.
- `capture_golden.py --auto` sets the scope span and mode itself over CAT
  (only those two settings, through the whitelisted `scripts/dev_cat.py`),
  confirms every case from both the CAT readback and the scope stream, and
  restores your original span and mode, even after an error or Ctrl-C.
  Operator-only cases (transmit, power-on, USB re-plug) are skipped; run those
  later in the interactive mode with `--only tx-dummy-load power-on-startup usb-replug`.

Try both without a radio: `hardware_smoke.py --dry-run --minutes 0.2` and
`capture_golden.py --auto --dry-run`.

On macOS, FTDI's libraries (`libft4222.dylib` with D2XX built in, and
`libftd2xx.dylib`) can't be downloaded by script from ftdichip.com, because of
a browser challenge. For local bench use they can be taken unmodified from the
`osx/` folder of the `ft4222` source package on PyPI. See THIRD_PARTY.md.
