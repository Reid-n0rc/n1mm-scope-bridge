# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import os
import socket
from collections.abc import Iterator

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


@pytest.fixture
def listener() -> Iterator[socket.socket]:
    """A loopback UDP socket standing in for N1MM+ (bind port 0, 5 s timeout)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(5)
        yield rx
