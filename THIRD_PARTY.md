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
- License: GPLv3 (`LICENSE` in that repository; "GPLv3", no "or later"). This
  project is GPL-3.0-only, which is compatible.
- Copyright notices, reproduced verbatim:
  - README: "wfview is copyright 2017-2026 Elliott H. Liggett (W6EL) and Phil
    Taylor (M0VSE). All rights reserved. wfview source code is licensed via the
    GNU GPLv3."
  - `src/radio/yaesucommander.cpp`: "Copyright 2017-2024 Elliott H. Liggett
    W6EL and Phil E. Taylor M0VSE"
- Derived files. Each carries those notices, the GPL notice, and a dated
  "Modified by" notice (GPLv3 §5(a)):

  | File | Taken from wfview | Changes |
  |------|-------------------|---------|
  | `src/n1mm_scope_bridge/radios/yaesu_scope.py` | `include/packettypes.h` (`yaesu_scope_data`), `src/ft4222handler.cpp` (sync pattern), `src/radio/yaesucommander.cpp` (`haveScopeData()`) | Ported to Python as a pure parser, with validation added |
  | `src/n1mm_scope_bridge/transport/ft4222.py` | `src/ft4222handler.cpp`, `include/ft4222handler.h` (library names, device setup sequence, sync/resync) | Rewritten with ctypes; sliding-window resync; errors raised; device released only by the reading thread |
  | `src/n1mm_scope_bridge/radios/ft710.py` | `rigs/FT-710.rig` (span and scope-mode tables) | Converted from Qt INI to a `RadioProfile` |
  | `docs/protocol-yaesu-ft4222.md` | The same sources | Documentation of the protocol facts |

- How we meet GPLv3: see issue #12. In short, notices are kept (§4, §5),
  modifications are marked (§5(a)), the whole project is GPL-3.0-only
  (§5(c)), the CLI shows legal notices (`--version`, `--license`; §5(d)),
  and every release ships the source next to any binary (§6). `LICENSE`,
  `NOTICE`, and this file are included in the sdist and wheel.

### FTDI LibFT4222 / D2XX in CI (downloaded, not distributed)

- CI on Windows downloads FTDI's `LibFT4222-v1.4.8.zip` and the CDM driver
  package from ftdichip.com (`scripts/fetch_ftdi.py`, SHA-256 pinned, cached)
  to test the real native boundary (#37). The DLLs exist only on the CI
  runner under FTDI's licence ("may be used only in conjunction with products
  based on FTDI parts"; redistributable only with licence information
  unmodified). They are never committed, cached in artifacts, or bundled.

### FTDI LibFT4222 / D2XX (runtime dependency, not included)

- Source: <https://ftdichip.com/products/ft4222h/>
- License: FTDI's proprietary driver licence. It is **never bundled** in this
  repository or in any release. Users install it from FTDI, and the bridge
  loads it at run time. Bundling it would mean distributing GPL code
  (including wfview's) combined with a GPL-incompatible library, which we
  don't do without written permission from the wfview copyright holders.

### PySide6 / Qt 6 (GUI dependency)

- Source: <https://pypi.org/project/PySide6-Essentials/> (Qt for Python, The Qt Company)
- License: offered under LGPL-3.0-only, GPL-2.0-only, or GPL-3.0-only. This
  project uses it under **GPL-3.0-only**, which matches its own license.
- Use: the optional `gui` extra. The Windows build (#6) bundles the Qt
  libraries as separate DLLs (PyInstaller one-folder build). The release ships
  the Qt license texts and this notice. No Qt code is copied into this
  repository.

### PyInstaller bootloader (Windows build)

- Source: <https://pyinstaller.org> (PyPI `pyinstaller`, `packaging` dependency group)
- License: GPL-2.0-or-later with the PyInstaller bootloader exception, which
  allows the bootloader to be distributed with programs under any license.
- Use: `scripts/build_windows_app.py` / `packaging/windows/n1mm_scope_bridge.spec`
  build the one-folder Windows app (#6). The bootloader is embedded in the
  executables. The app ships `LICENSE`, `NOTICE`, and this file in
  `licenses/` (plus the Qt license texts once the GUI is bundled).

### pytest-qt (development only, not distributed)

- Source: <https://pypi.org/project/pytest-qt/>; license: MIT.

### N1MM Logger+ external spectrum interface (facts only)

- Source: <https://n1mmwp.hamdocs.com/appendices/external-udp-broadcasts/>
- Used for: the `<Spectrum>` XML element names and UDP port 13064. No code
  is copied.
