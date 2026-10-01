# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import os

import pytest

# GUI tests run headless everywhere (CI and local) unless a platform is forced.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Hardware tests run only with N1MM_BRIDGE_HARDWARE=1 (never in CI)."""
    if os.environ.get("N1MM_BRIDGE_HARDWARE") == "1":
        return
    skip = pytest.mark.skip(reason="set N1MM_BRIDGE_HARDWARE=1 with an FT-710 connected")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)
