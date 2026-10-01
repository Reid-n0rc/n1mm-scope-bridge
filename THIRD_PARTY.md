# Third-party material and notices

This file is the **single ledger** of material from other projects that is
copied into, adapted into, or bundled with this repository or its releases.
Third-party material keeps its original license.

## When an entry is required

Add an entry **in the same PR** whenever you:

- copy or adapt source code, tables, or data structures from another project;
- bundle a dependency whose code ends up in a released artifact (for example
  in a Windows standalone build).

No entry is needed for facts learned from a source (a byte offset, a sync
pattern, a UDP port) when nothing is copied. Cite those sources in the code
comment, the issue, or the doc instead.

## Rules

1. Check the license in the source's actual `LICENSE` file and file headers.
2. Allowed: material under licenses compatible with **GPL-3.0-only**
   (GPL-3.0, LGPL-2.1+/3.0, MIT, BSD, ISC, Apache-2.0, zlib).
3. Not allowed: unknown, proprietary, or incompatible licenses, including
   GPL-2.0-only code, FTDI library binaries in the repository, and N1MM+
   binaries or decompiled code.

## Entries

### wfview

- Source: <https://gitlab.com/eliggett/wfview>, reviewed at commit
  `cd18ea55fe479eb4526d1732b443cbfc3969c540` (2026-05-28)
- Copyright: 2017-2026 Elliott H. Liggett (W6EL) and Phil E. Taylor (M0VSE)
- License: GPLv3 (`LICENSE` in that repository)
- Used for: the FT-710 FT4222 SPI scope protocol, namely the frame layout
  (`include/packettypes.h`, `yaesu_scope_data`), the sync pattern and device
  setup (`src/ft4222handler.cpp`), the status-byte decoding
  (`src/radio/yaesucommander.cpp`, `haveScopeData()`), and the span and
  scope-mode tables (`rigs/FT-710.rig`). Any code ported from these files
  carries a header comment naming the file it came from.

### FTDI LibFT4222 / D2XX (runtime dependency, not included)

- Source: <https://ftdichip.com/products/ft4222h/>
- License: FTDI driver licence terms. Users install it themselves. It is not
  committed to this repository, and it will only be bundled in a release
  build if the release PR records the licence review here.

### N1MM Logger+ external spectrum interface (facts only)

- Source: <https://n1mmwp.hamdocs.com/appendices/external-udp-broadcasts/>
- Used for: the `<Spectrum>` XML element names and UDP port 13064. No code
  is copied.
