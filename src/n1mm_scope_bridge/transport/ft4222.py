# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
# SPDX-FileCopyrightText: 2017-2026 Elliott H. Liggett (W6EL) and Phil Taylor (M0VSE)
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see <https://www.gnu.org/licenses/>.
#
# Portions derived from wfview (https://gitlab.com/eliggett/wfview):
#   wfview is copyright 2017-2026 Elliott H. Liggett (W6EL) and Phil Taylor
#   (M0VSE). All rights reserved. wfview source code is licensed via the GNU
#   GPLv3.
#
# Modified by Reid Crowe, N0RC, 2026-10-01: ported from C++/Qt to Python.
#   Library names and the device setup sequence (open by description, timeouts,
#   latency, SPI master parameters, system clock) are taken from
#   src/ft4222handler.cpp and include/ft4222handler.h. Rewritten with ctypes
#   instead of QLibrary; resync locks on the 4-byte sync, skips repeated sync
#   padding, and keeps the bytes that follow as the start of the next frame
#   (wfview waits for 16 pattern bytes and can lock mid-padding); I/O errors
#   raise instead of emitting the buffer;
#   the device is released only by the reading thread.
"""Read raw scope frames from a Yaesu radio's FT4222 USB-to-SPI bridge.

Derived from wfview; see the header above and THIRD_PARTY.md.

FTDI's LibFT4222 and D2XX libraries are proprietary. They are never bundled;
the user installs them from FTDI and they are loaded here at run time. ctypes
releases the GIL during each foreign call, so a blocking SPI read runs in
parallel with the rest of the pipeline (docs/architecture.md, Concurrency).
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterator
from typing import Any, Protocol

from n1mm_scope_bridge.radios.yaesu_scope import FRAME_SIZE, SYNC

FTDI_DOWNLOAD_URL = "https://ftdichip.com/products/ft4222h/"
DEFAULT_DESCRIPTION = "FT4222 A"
RESYNC_PATTERN = SYNC * 4  # wfview's inter-frame pattern (sync padding)
MAX_RESYNC_BYTES = 8192
MAX_REINITS = 3
MAX_RESYNCS = 16  # resyncs in a row without a valid frame before re-opening

FT_OK = 0
FT_OPEN_BY_DESCRIPTION = 2
SPI_IO_SINGLE = 1
CLK_DIV_64 = 6
CLK_IDLE_HIGH = 1
CLK_LEADING = 0
SYS_CLK_24 = 1
READ_TIMEOUT_MS = 100
WRITE_TIMEOUT_MS = 100
LATENCY_MS = 2
SS_MASK = 0x01

FT_STATUS_NAMES = {
    0: "FT_OK",
    1: "FT_INVALID_HANDLE",
    2: "FT_DEVICE_NOT_FOUND",
    3: "FT_DEVICE_NOT_OPENED",
    4: "FT_IO_ERROR",
    5: "FT_INSUFFICIENT_RESOURCES",
    6: "FT_INVALID_PARAMETER",
}


def status_name(status: int) -> str:
    return FT_STATUS_NAMES.get(status, f"status {status}")


class Ft4222Error(RuntimeError):
    """The FT4222 device or library failed."""


class LibraryNotFound(Ft4222Error):
    pass


class DeviceNotFound(Ft4222Error):
    pass


class Ft4222Api(Protocol):
    """The handful of D2XX/LibFT4222 calls the reader needs, as plain Python."""

    def open_ex(self, description: str) -> tuple[int, Any]:
        """Open by description; return (status, handle)."""

    def set_timeouts(self, handle: Any, read_ms: int, write_ms: int) -> int:
        """FT_SetTimeouts."""

    def set_latency_timer(self, handle: Any, ms: int) -> int:
        """FT_SetLatencyTimer."""

    def spi_master_init(self, handle: Any) -> int:
        """FT4222_SPIMaster_Init with wfview's parameters."""

    def set_clock(self, handle: Any) -> int:
        """FT4222_SetClock(SYS_CLK_24)."""

    def spi_read(self, handle: Any, size: int) -> tuple[int, bytes]:
        """FT4222_SPIMaster_SingleRead; return (status, data)."""

    def uninitialize(self, handle: Any) -> int:
        """FT4222_UnInitialize."""

    def close(self, handle: Any) -> int:
        """FT_Close."""


# D2XX's DWORD/ULONG/FT_STATUS are 32-bit on every platform; FT4222 enums are ints.
_U32 = ctypes.c_uint32
_HANDLE = ctypes.c_void_p


def _sig(fn: Any, restype: Any, *argtypes: Any) -> Any:
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


class CtypesApi:
    """``Ft4222Api`` backed by the real FTDI libraries via ctypes."""

    def __init__(self, d2xx: Any, ft4222: Any) -> None:
        self._open = _sig(d2xx.FT_OpenEx, _U32, ctypes.c_char_p, _U32, ctypes.POINTER(_HANDLE))
        self._close = _sig(d2xx.FT_Close, _U32, _HANDLE)
        self._timeouts = _sig(d2xx.FT_SetTimeouts, _U32, _HANDLE, _U32, _U32)
        self._latency = _sig(d2xx.FT_SetLatencyTimer, _U32, _HANDLE, ctypes.c_ubyte)
        self._uninit = _sig(ft4222.FT4222_UnInitialize, _U32, _HANDLE)
        self._spi_init = _sig(
            ft4222.FT4222_SPIMaster_Init,
            _U32,
            _HANDLE,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_ubyte,
        )
        self._read = _sig(
            ft4222.FT4222_SPIMaster_SingleRead,
            _U32,
            _HANDLE,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_uint16,
            ctypes.POINTER(ctypes.c_uint16),
            ctypes.c_int,
        )
        self._clock = _sig(ft4222.FT4222_SetClock, _U32, _HANDLE, ctypes.c_int)

    def open_ex(self, description: str) -> tuple[int, Any]:
        handle = _HANDLE()
        status = self._open(
            description.encode("ascii"), FT_OPEN_BY_DESCRIPTION, ctypes.pointer(handle)
        )
        return int(status), handle

    def set_timeouts(self, handle: Any, read_ms: int, write_ms: int) -> int:
        return int(self._timeouts(handle, read_ms, write_ms))

    def set_latency_timer(self, handle: Any, ms: int) -> int:
        return int(self._latency(handle, ms))

    def spi_master_init(self, handle: Any) -> int:
        return int(
            self._spi_init(handle, SPI_IO_SINGLE, CLK_DIV_64, CLK_IDLE_HIGH, CLK_LEADING, SS_MASK)
        )

    def set_clock(self, handle: Any) -> int:
        return int(self._clock(handle, SYS_CLK_24))

    def spi_read(self, handle: Any, size: int) -> tuple[int, bytes]:
        buf = (ctypes.c_ubyte * size)()
        got = ctypes.c_uint16(0)
        status = self._read(handle, buf, size, ctypes.pointer(got), 0)
        return int(status), bytes(buf[: got.value])

    def uninitialize(self, handle: Any) -> int:
        return int(self._uninit(handle))

    def close(self, handle: Any) -> int:
        return int(self._close(handle))


Loader = Callable[[str], Any]

_ADD_DLL_DIRECTORY: Callable[[str], object] | None = getattr(os, "add_dll_directory", None)


def library_names(
    platform: str = sys.platform, is_64bit: bool = sys.maxsize > 2**32
) -> tuple[list[str], list[str]]:
    """Candidate ``(d2xx, ft4222)`` library names, in the order wfview tries them.

    Windows is the supported platform (N1MM+ is Windows-only). The macOS and
    Linux names keep the code portable for future uses but are untested. An
    empty d2xx list means D2XX is built into the FT4222 library.
    """
    if platform == "win32":
        first, second = "LibFT4222-64.dll", "LibFT4222.dll"
        return ["ftd2xx.dll"], [first, second] if is_64bit else [second, first]
    if platform == "darwin":
        return ["libftd2xx.dylib"], ["libft4222.dylib"]
    return [], ["libft4222.so"]


def _default_loader(name: str) -> Any:  # pragma: no cover - needs the real libraries
    # FTDI exports use __stdcall on Windows (wfview's FTAPI); cdecl elsewhere.
    loader = getattr(ctypes, "WinDLL", ctypes.CDLL)
    return loader(name)


def _load_first(names: list[str], lib_dir: str | None, loader: Loader, tried: list[str]) -> Any:
    for name in names:
        path = os.path.join(lib_dir, name) if lib_dir else name
        tried.append(path)
        try:
            return loader(path)
        except OSError:
            continue
    return None


def load_api(
    lib_dir: str | None = None,
    *,
    platform: str = sys.platform,
    is_64bit: bool = sys.maxsize > 2**32,
    loader: Loader = _default_loader,
    add_dll_directory: Callable[[str], object] | None = _ADD_DLL_DIRECTORY,
) -> CtypesApi:
    """Load LibFT4222 (and D2XX where it is separate) and return the bound API."""
    if lib_dir and not os.path.isdir(lib_dir):
        raise LibraryNotFound(f"FTDI library folder does not exist: {lib_dir}")
    d2xx_names, ft_names = library_names(platform, is_64bit)
    tried: list[str] = []
    if platform == "win32":
        # LibFT4222 links against ftd2xx.dll; Python 3.8+ does not search the
        # DLL's own folder for dependencies, so register it, then load D2XX first.
        if lib_dir and add_dll_directory is not None:
            add_dll_directory(lib_dir)
        d2xx = _load_first(d2xx_names, lib_dir, loader, tried)
        ft4222 = _load_first(ft_names, lib_dir, loader, tried)
    else:
        ft4222 = _load_first(ft_names, lib_dir, loader, tried)
        d2xx = ft4222 if ft4222 is not None and hasattr(ft4222, "FT_OpenEx") else None
        if ft4222 is not None and d2xx is None:
            d2xx = _load_first(d2xx_names, lib_dir, loader, tried)
    if ft4222 is None or d2xx is None:
        raise LibraryNotFound(
            "Could not load FTDI's LibFT4222/D2XX libraries (tried: "
            + ", ".join(tried)
            + f"). Install them from {FTDI_DOWNLOAD_URL} or set the FTDI library folder."
        )
    try:
        return CtypesApi(d2xx, ft4222)
    except AttributeError as err:
        raise LibraryNotFound(f"FTDI library is missing a required function: {err}") from err


class Ft4222Reader:
    """Opens the radio's FT4222 and yields validated raw frames.

    Iterate it from one thread (the pipeline's reader). ``stop()`` may be
    called from any thread: it only sets a flag, and the reading thread
    releases the device after its current read (at most ``READ_TIMEOUT_MS``).
    """

    def __init__(
        self,
        api: Ft4222Api,
        *,
        description: str = DEFAULT_DESCRIPTION,
        frame_size: int = FRAME_SIZE,
        max_resync_bytes: int = MAX_RESYNC_BYTES,
    ) -> None:
        self._api = api
        self._description = description
        self._frame_size = frame_size
        self._max_resync = max_resync_bytes
        self._handle: Any = None
        self._stop = threading.Event()
        self.resyncs = 0
        self.reinits = 0

    @property
    def api(self) -> Ft4222Api:
        """The FTDI (or emulator) API this reader uses."""
        return self._api

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    def open(self) -> None:
        self._release()
        status, handle = self._api.open_ex(self._description)
        if status != FT_OK:
            raise DeviceNotFound(
                f"Could not open {self._description!r} ({status_name(status)}). Is the radio "
                "on and connected by USB, with FTDI's D2XX driver installed?"
            )
        self._handle = handle
        steps: list[tuple[str, Callable[[], int]]] = [
            (
                "FT_SetTimeouts",
                lambda: self._api.set_timeouts(handle, READ_TIMEOUT_MS, WRITE_TIMEOUT_MS),
            ),
            ("FT_SetLatencyTimer", lambda: self._api.set_latency_timer(handle, LATENCY_MS)),
            ("FT4222_SPIMaster_Init", lambda: self._api.spi_master_init(handle)),
            ("FT4222_SetClock", lambda: self._api.set_clock(handle)),
        ]
        for name, step in steps:
            status = step()
            if status != FT_OK:
                self._release()
                raise Ft4222Error(f"{name} failed ({status_name(status)})")

    def _read(self, size: int) -> bytes:
        status, data = self._api.spi_read(self._handle, size)
        if status != FT_OK:
            raise Ft4222Error(f"FT4222_SPIMaster_SingleRead failed ({status_name(status)})")
        return data

    def resync(self) -> bytes | None:
        """Find the next frame boundary; return the first bytes of the next frame.

        Reads byte by byte until the 4-byte sync marker, then consumes any
        repeats of it (frames may be padded with the sync pattern; wfview
        waits for four repeats). The first 4-byte group that is not the
        pattern starts the next frame. Returns None if the stream ends or no
        sync is found within ``max_resync_bytes``.
        UNVERIFIED (#36): the real radio's padding between frames.
        """
        window: deque[int] = deque(maxlen=len(SYNC))
        for _ in range(self._max_resync):
            byte = self._read(1)
            if len(byte) != 1:
                return None
            window.append(byte[0])
            if bytes(window) == SYNC:
                for _ in range(self._max_resync // len(SYNC)):
                    group = self._read(len(SYNC))
                    if len(group) != len(SYNC):
                        return None
                    if group != SYNC:
                        return group
                return None
        return None

    def read_frame(self) -> bytes | None:
        """Return the next whole frame, resynchronising (or re-opening) as needed.

        Returns None if ``stop()`` was called during recovery. After
        ``MAX_RESYNCS`` resyncs without a valid frame the device is re-opened,
        and after ``MAX_REINITS`` re-opens ``Ft4222Error`` is raised, so neither
        a silent nor a garbled stream can become an endless busy loop.
        """
        if self._handle is None:
            raise Ft4222Error("device is not open")
        failed_reinits = 0
        resyncs_without_frame = 0
        prefix = b""
        while not self._stop.is_set():
            data = prefix + self._read(self._frame_size - len(prefix))
            if len(data) == self._frame_size and data.endswith(SYNC):
                return data
            self.resyncs += 1
            resyncs_without_frame += 1
            found = self.resync()
            if found is not None and resyncs_without_frame < MAX_RESYNCS:
                prefix = found
                continue
            prefix = b""
            resyncs_without_frame = 0
            if failed_reinits >= MAX_REINITS:
                raise Ft4222Error(
                    f"No valid scope frames from {self._description!r} after "
                    f"{MAX_REINITS} re-opens. Is the radio's scope running?"
                )
            failed_reinits += 1
            self.reinits += 1
            self.open()
        return None

    def stop(self) -> None:
        self._stop.set()

    def __iter__(self) -> Iterator[bytes]:
        try:
            if self._handle is None:
                self.open()
            while not self._stop.is_set():
                frame = self.read_frame()
                if frame is None:
                    return
                yield frame
        finally:
            self._release()

    def _release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            self._api.uninitialize(handle)
            self._api.close(handle)

    def close(self) -> None:
        """Stop and release. Call from the reading thread, or after it finished."""
        self.stop()
        self._release()
