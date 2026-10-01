# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""PyInstaller entry point for the console CLI (n1mm-scope-bridge.exe)."""

from n1mm_scope_bridge.cli import main

raise SystemExit(main())
