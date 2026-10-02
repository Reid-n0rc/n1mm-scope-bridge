# Yaesu FT-710 scope over FT4222 SPI

Everything here comes from wfview's reverse engineering (see
[THIRD_PARTY.md](../THIRD_PARTY.md)): `src/ft4222handler.cpp`,
`include/packettypes.h`, `src/radio/yaesucommander.cpp` (`haveScopeData()`),
and `rigs/FT-710.rig`. Items marked **UNVERIFIED** have not yet been confirmed
by this project on real hardware.

## USB device

When connected over USB, and with the radio menu **OPERATION SETTING → GENERAL
→ SCU-LAN10** set to **ON** (CAT `EX030126;` reads `EX0301261;`), the FT-710
enumerates an FTDI **FT4222** (USB ID 0403:601c, "FT4222H") in addition to the
CAT and audio devices. With SCU-LAN10 OFF (`EX0301260;`) the FT4222 is not
present at all: verified on a real FT-710 on 2026-10-02, whose USB tree then
showed only the CP2105 dual UART and the USB audio codec. The SCU-LAN10
adapter itself is not needed. Source for the requirement: wfview's FT-710
setup page; menu number from Yaesu's FT-710 CAT manual (EX menu 03-01-26). wfview opens it with D2XX by description
**`"FT4222 A"`** and sets it up as follows:

| Step | Call | Value |
|------|------|-------|
| Open | `FT_OpenEx("FT4222 A", FT_OPEN_BY_DESCRIPTION)` | |
| Timeouts | `FT_SetTimeouts` | 100 ms read, 100 ms write |
| Latency | `FT_SetLatencyTimer` | 2 ms |
| SPI | `FT4222_SPIMaster_Init` | single I/O, `CLK_DIV_64`, CPOL idle high, CPHA leading edge, SS mask `0x01` |
| Clock | `FT4222_SetClock` | `SYS_CLK_24` |
| Read | `FT4222_SPIMaster_SingleRead` | 4096 bytes, `isEndTransaction=false` |

Library names: Windows loads `ftd2xx.dll` plus `LibFT4222-64.dll` (or
`LibFT4222.dll` on 32-bit). Linux loads `libft4222.so`, which includes D2XX.
macOS loads `libft4222.dylib`, plus `libftd2xx.dylib` if D2XX is not built in.

## Frame layout (4096 bytes)

| Offset | Length | Field |
|-------:|-------:|-------|
| 0 | 850 | `wf1`, main receiver spectrum. Each byte is **bit-inverted** (`~b`). After inversion, 0–255 with higher meaning stronger |
| 850 | 850 | `wf2`, sub receiver (dual-receiver radios only; unused on the FT-710) |
| 1700 | 200 | `audio1fft` |
| 1900 | 400 | `audio1scope` |
| 2300 | 200 | `audio2fft` |
| 2500 | 400 | `audio2scope` |
| 2900 | 150 | `data`, the status block (below) |
| 3050 | 1042 | unused |
| 4092 | 4 | sync, `FF 01 EE 01` |

### Resynchronisation

A frame is valid only if it ends with `FF 01 EE 01`.

- **wfview** reads 1 byte at a time (up to 8192) until it sees 16 bytes of
  `FF 01 EE 01` repeated four times, then resumes 4096-byte reads.
- **This bridge** locks on a single `FF 01 EE 01`, consumes any further
  repeats (padding), and treats the next 4 bytes as the start of the next
  frame.

The difference matters. If the radio pads the unused region with the
pattern, wfview can lock in the middle of the padding and accept frames
shifted by up to 1 KiB. If the radio does not pad, wfview never finds 16
pattern bytes. The bridge handles both cases (tested with the emulator's
`padding="sync"` and `padding="zero"`). After 16 resyncs without a valid frame
it re-opens the device, and after 3 re-opens it reports
`No valid scope frames`. **Verified on a real FT-710 (#111):** the bytes between the
status block and the end are zero, and each frame ends with `FF 01 EE 01` four
times (16 bytes), which is what wfview's 16-byte resync waits for. Frames arrived
aligned from the first read.

### Status block (`data`, offsets relative to byte 2900)

| Offset | Length | Meaning |
|-------:|-------:|---------|
| 17 | 1 | Scope mode. wfview uses the first hex digit of the byte as the mode code (table below) |
| 22 | 2 | Changes on TX (`00 08` → `80 28`) |
| 27 | 1 | Preamp (2 bits) and attenuator (2 bits) |
| 32 | 1 | Low nibble: scope span index, 0–9 (table below), in every mode. High nibble: `0x4` in Cursor mode, `0x8` in Fixed mode, `0x0` in Center (verified #111) |
| 33 | 1 | Scope speed (upper nibble?), **UNVERIFIED** |
| 52 | 1 | Scope mode family: `00` center, `01` cursor, `02` fixed (verified #111) |
| 60 | 1 | VFO-A operating mode (scope code) |
| 64 | 5 | VFO-A frequency, **packed BCD**, Hz (for example `00 14 07 40 00` = 14.074000 MHz) |
| 85 | 1 | VFO-B operating mode |
| 89 | 5 | VFO-B frequency, packed BCD, Hz |
| 110 | 1 | S-meter |
| 132 | 4 | VFO-A frequency, big-endian binary (verified #111) |
| 144 | 4 | Scope start frequency, big-endian: the fixed start (for example 7,000,000) in Fixed mode, VFO-A otherwise (verified #111) |

### Span index (byte 32)

| Index | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|------|---|---|---|---|---|---|---|---|---|---|
| Span | 1 kHz | 2 kHz | 5 kHz | 10 kHz | 20 kHz | 50 kHz | 100 kHz | 200 kHz | 500 kHz | 1 MHz |

### Scope mode code (byte 17, first hex digit)

| Code | Mode | Code | Mode |
|---|---|---|---|
| 0 | 3DSS Center | 6 | Cursor (Expand) |
| 1 | 3DSS Cursor | 7 | Cursor (Normal) |
| 2 | 3DSS Fixed | 8 | Cursor (Expand) |
| 3 | Center (Expand) | 9 | Fixed (Expand) |
| 4 | Center (Normal) | A | Fixed (Normal) |
| 5 | Center (Expand) | | |

### Frequency edges

wfview always computes the edges as `VFO-A ± span/2`. That is correct in
**Center** mode. In **Cursor** and **Fixed** modes it is probably wrong:
Fixed mode likely uses the start frequency at offset 144. Until hardware
validation confirms this, the bridge:

- uses `VFO-A ± span/2` in Center mode;
- in other modes, sends the same edges and logs a rate-limited warning
  telling the operator to use Center mode.

### Rate

Measured on a real FT-710 (#111): **11.2 frames per second** (3365 frames in
300 s). The emulator streams at the same rate (`EMULATOR_FPS`).


The radio streams frames continuously. wfview emits one frame every
`poll` ms (20 ms by default, adjusted to the UI's update interval). The bridge
drops frames to the N1MM rate (default 4 per second) and can optionally
average or peak-hold the dropped frames.


## Validation on a real FT-710 (#111, 2026-10-02)

- **Enabling the scope output:** menu **OPERATION SETTING → GENERAL → SCU-LAN10 = ON**
  (CAT `EX0301261;`). After changing it the FT4222 (`0403:601C`, "FT4222") only
  appeared on USB after a radio power cycle **and** unplugging and replugging the
  USB cable.
- **Smoke test:** 5 minutes streaming through the bridge: 3365 frames (11.2/s),
  1200/1200 N1MM+ packets, 0 dropped or bad frames, 0 resyncs, 30/30 CAT VFO
  checks matched.
- **Golden captures** (`tests/fixtures/golden/`, 7.074 MHz DATA-U): all 10
  Center-mode spans plus Cursor and Fixed decode exactly as CAT reports them.
  Transmit, power-on start-up, and USB re-plug cases still need an operator.
- **Noise floor** rises with span (10th percentile about 37 at 1 kHz to 90 at
  1 MHz); the emulator uses the measured values.
- **Still UNVERIFIED:** exact Cursor-mode edges (the cursor position isn't
  decoded; edges stay VFO-centred), transmit flags, and byte 33 (speed).
