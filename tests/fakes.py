# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Shared test doubles."""

from __future__ import annotations

from typing import Any

from n1mm_scope_bridge.transport import ft4222 as ft

HANDLE = object()


class FakeApi:
    """Scripted Ft4222Api: serves bytes from ``stream`` and records calls."""

    def __init__(self, stream: bytes = b"", *, repeat: bytes = b"", **status: int) -> None:
        self.stream = bytearray(stream)
        self.repeat = repeat  # served forever once ``stream`` is exhausted, like a live radio
        self.status = status
        self.calls: list[tuple[Any, ...]] = []
        self.read_error_after: int | None = None
        self.reads = 0

    def _st(self, name: str) -> int:
        return self.status.get(name, ft.FT_OK)

    def open_ex(self, description: str) -> tuple[int, Any]:
        self.calls.append(("open", description))
        return self._st("open"), HANDLE

    def set_timeouts(self, handle: Any, read_ms: int, write_ms: int) -> int:
        self.calls.append(("timeouts", read_ms, write_ms))
        return self._st("timeouts")

    def set_latency_timer(self, handle: Any, ms: int) -> int:
        self.calls.append(("latency", ms))
        return self._st("latency")

    def spi_master_init(self, handle: Any) -> int:
        self.calls.append(("spi_init",))
        return self._st("spi_init")

    def set_clock(self, handle: Any) -> int:
        self.calls.append(("clock",))
        return self._st("clock")

    def spi_read(self, handle: Any, size: int) -> tuple[int, bytes]:
        assert handle is HANDLE
        self.reads += 1
        if self.read_error_after is not None and self.reads > self.read_error_after:
            return 4, b""
        if not self.stream and self.repeat:
            self.stream = bytearray(self.repeat)
        data, self.stream = bytes(self.stream[:size]), self.stream[size:]
        return ft.FT_OK, data

    def uninitialize(self, handle: Any) -> int:
        self.calls.append(("uninit",))
        return ft.FT_OK

    def close(self, handle: Any) -> int:
        self.calls.append(("close",))
        return ft.FT_OK
