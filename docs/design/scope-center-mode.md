# Design: switch the scope to Center mode while streaming (#62)

Status: **decided: no CAT.** The maintainer requires that the bridge never
open either FT-710 COM port, because N1MM+ needs both (Enhanced for CAT,
Standard for PTT/keying). N1MM+ offers no interface to send a CAT command on
the bridge's behalf (below), so the bridge **prompts the operator** to set
Center and **confirms it from the scope frame** (status byte 17)
(`src/n1mm_scope_bridge/center.py`). `tests/test_no_com_ports.py` enforces
that no COM port is ever opened. The CAT research below is kept for
reference.

## Problem

The bridge's frequency edges are exact only in the FT-710's **Center** scope
mode (docs/protocol-yaesu-ft4222.md). The option `force_center_mode` (off by
default) switches the scope to Center when streaming starts and restores the
operator's previous mode when it stops.

## The CAT command (research)

- wfview `rigs/FT-710.rig`, command 68 "Scope Mode": string `SS06`, 5
  parameter bytes, left-justified (padded right with `0`), get and set
  supported. wfview sends the mode code as one character: `SS06` + code +
  `0000` + `;`.
- Yaesu's FTDX10 CAT manual (same command family) agrees. `SS P1 P2 P3 P4–P7;`
  with P1=0 and P2=6 is MODE. P3 values: `0` 3DSS CENTER, `1` 3DSS CURSOR,
  `2` 3DSS FIX, `3`/`4`/`5` W/F CENTER, `6`/`7`/`8` W/F CURSOR,
  `9`/`A`/`B` W/F FIX. P4–P7 are `0`.
  - Set Center (Normal): `SS0640000;`
  - Read: `SS06;` → `SS06<P3>0000;`
- The mode code is the same one the bridge already decodes from the scope
  frame (status byte 17, first hex digit). So the previous mode can be read
  from the frames, with **no CAT read needed**.
- UNVERIFIED (#62): that the FT-710 accepts exactly this string. FT-710 menu
  labels differ slightly from the FTDX10 (wfview's table stops at `A`).

## How the bridge could send it (research)

| Path | Finding | Verdict |
|---|---|---|
| Ask N1MM+ over UDP | N1MM+ accepts only `<radio_setfrequency>` and `<Spectrum>` inbound (N1MM+ manual, External UDP Messages); there is no raw CAT command | Not possible |
| N1MM+ macro `{CAT1ASC SS0640000;}` | Works through N1MM+'s own CAT connection, but only when the **operator** presses the key | Document as a manual alternative |
| FT-710 second virtual COM port ("Standard COM Port") | Yaesu documents it on the FTDX10 as **TX controls only** (PTT, CW keying, digital), not CAT. Opening a COM port on Windows asserts DTR/RTS by default, which, with the radio's PTT/keying set to RTS/DTR, **would key the transmitter** | Only if a hardware test proves it accepts CAT, **and** the port is opened with DTR/RTS held low. UNVERIFIED (#62) |
| Enhanced (CAT-1) port while N1MM+ is closed | Works, but N1MM+ normally holds it, so a restore at exit would usually fail | Fallback only; not automatic |
| Bridge owns CAT and shares it with N1MM+ (virtual port pair) | Large, separate feature | Out of scope |

## Superseded design (CAT path, not implemented)

- **`CatControl` protocol** (`cat.py`), with one method:
  `set_scope_mode(code: str) -> None`. Implementations must send **only** the
  scope-mode command. There is no generic "send CAT" method, so nothing else
  (and nothing that transmits) can be sent through it.
- **`ScopeModeKeeper`**, driven by the stream session:
  - On start, if `force_center_mode` is on, remember the mode from the first
    frame's status. If that mode isn't Center, send Center (`4`).
  - While streaming, if the operator changes the scope mode away from Center,
    **do not fight it**. Stop managing, and don't restore over the
    operator's choice.
  - On stop, exit, Ctrl-C, or a stream error, restore the remembered mode if
    the scope is still in the Center mode we set.
  - Restoring can't happen after a power cut or a killed process. The docs
    say so.
- **Emulator implementation** that applies the command to `RadioState`, so the
  tests verify set and restore end to end through the real frame stream.
- **Real serial implementation:** follow-up issue. It needs hardware
  confirmation of the CAT path, DTR/RTS forced low before the port opens, and
  a `hardware`-marked test. Until then, enabling the option with a real radio
  reports that it is not yet available.

## Out of scope

Bridge-owned CAT sharing; any other CAT command.
