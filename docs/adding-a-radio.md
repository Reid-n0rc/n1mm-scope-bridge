# Adding a radio

A radio is supported when the bridge can turn its scope data into a
`SpectrumFrame` (frequency edges in Hz and integer levels). Each radio is
**one issue** (see AGENTS.md, Task sizing). If a radio needs a new transport
(for example a network protocol), the transport is a separate issue first.

## 1. Gather evidence (no code yet)

Open a **Radio support request** with:

- the model and firmware version;
- how the radio exposes scope data: USB FT4222 SPI (as on the FT-710), a CAT
  command stream, or a network protocol (for example Yaesu SCU-LAN10);
- whether wfview supports the radio's scope. If it does, give the rig file
  (`rigs/<MODEL>.rig`) and its `HasSpectrum`, `SpectrumLenMax`,
  `SpectrumAmpMax`, and span table;
- a short capture (`n1mm-scope-bridge record --frames 20`, once that command
  exists), with notes on the frequency, span, and scope mode the radio showed.

## 2. Plan it (Implementation task)

List exactly the files involved. That is usually:

- `src/n1mm_scope_bridge/radios/<model>.py`: the profile (span table, mode
  table, frame size), reusing a shared parser where possible;
- `tests/test_<model>.py` plus a trimmed fixture under `tests/fixtures/`;
- a row in the README's *Supported radios* table;
- a `THIRD_PARTY.md` entry if anything is ported from wfview.

## 3. Rules

- Cite every byte offset's source (wfview file and function, or your own
  capture).
- Mark anything not confirmed on the real radio as `# UNVERIFIED:`.
- Never send commands that change radio state.
