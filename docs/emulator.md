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

The emulator implements what we know from wfview's code. What we don't yet
know is marked `UNVERIFIED (#36)`:

- **Padding between the status block and the sync tail.** wfview's resync
  waits for the sync pattern repeated four times, which suggests the radio
  pads frames with it. The emulator supports both `padding="sync"` (the
  default) and `padding="zero"`, and the reader handles both.
- **Frame rate**, start-up alignment, and how the stream behaves after a USB
  re-plug. The golden captures (below) record all of these.

Issue #36 records golden captures from a real FT-710 once and checks the
emulator against them in CI on every PR
(`tests/test_emulator_conformance.py`). Until the captures are committed,
those tests are expected failures marked "awaiting golden capture (#36)".
After that, the emulator is a checked stand-in for the radio. Changing the
parser (`radios/yaesu_scope.py`) or updating the radio firmware means
recapturing; the conformance test fails if the parser changed since the
captures were taken.

The emulator paces frames against a deadline, so it streams at exactly its
configured rate (20 frames/s, `EMULATOR_FPS`) however long a frame takes to
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
