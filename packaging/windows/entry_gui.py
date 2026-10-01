# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""PyInstaller entry point for the windowed GUI (N1MM Scope Bridge.exe).

Used only when ``n1mm_scope_bridge.gui.app`` exists (issue #18); the spec and
scripts/build_windows_app.py skip the GUI executable until then.
"""

from n1mm_scope_bridge.gui.app import main  # type: ignore[import-not-found,unused-ignore]

raise SystemExit(main())
