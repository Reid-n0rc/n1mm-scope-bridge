# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import ctypes
import os
import threading
from pathlib import Path
from typing import Any

import pytest
from frames import make_ft4222_frame

from n1mm_scope_bridge.transport import ft4222 as ft
from n1mm_scope_bridge.transport.ft4222 import (
    DeviceNotFound,
    Ft4222Error,
    Ft4222Reader,
    LibraryNotFound,
)

FRAME = make_ft4222_frame()
HANDLE = object()


class FakeApi:
    """Scripted Ft4222Api: serves bytes from ``stream`` and records calls."""

    def __init__(self, stream: bytes = b"", **status: int) -> None:
        self.stream = bytearray(stream)
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
        data, self.stream = bytes(self.stream[:size]), self.stream[size:]
        return ft.FT_OK, data

    def uninitialize(self, handle: Any) -> int:
        self.calls.append(("uninit",))
        return ft.FT_OK

    def close(self, handle: Any) -> int:
        self.calls.append(("close",))
        return ft.FT_OK


def names(api: FakeApi) -> list[str]:
    return [c[0] for c in api.calls]


# --- open / setup ----------------------------------------------------------------


def test_open_runs_wfview_setup_sequence() -> None:
    api = FakeApi()
    reader = Ft4222Reader(api)
    reader.open()
    assert reader.is_open
    assert api.calls == [
        ("open", "FT4222 A"),
        ("timeouts", 100, 100),
        ("latency", 2),
        ("spi_init",),
        ("clock",),
    ]


def test_open_device_not_found_has_helpful_message() -> None:
    reader = Ft4222Reader(FakeApi(open=2))
    with pytest.raises(DeviceNotFound, match=r"FT_DEVICE_NOT_FOUND.*connected by USB"):
        reader.open()
    assert not reader.is_open


@pytest.mark.parametrize(
    ("step", "label"),
    [
        ("timeouts", "FT_SetTimeouts"),
        ("latency", "FT_SetLatencyTimer"),
        ("spi_init", "FT4222_SPIMaster_Init"),
        ("clock", "FT4222_SetClock"),
    ],
)
def test_setup_step_failure_releases_device(step: str, label: str) -> None:
    api = FakeApi(b"", **{step: 4})
    reader = Ft4222Reader(api)
    with pytest.raises(Ft4222Error, match=f"{label} failed \\(FT_IO_ERROR\\)"):
        reader.open()
    assert names(api)[-2:] == ["uninit", "close"]
    assert not reader.is_open


def test_status_name_unknown_code() -> None:
    assert ft.status_name(1004) == "status 1004"


# --- reading -----------------------------------------------------------------------


def test_read_frame_returns_aligned_frame() -> None:
    reader = Ft4222Reader(FakeApi(FRAME * 2))
    reader.open()
    assert reader.read_frame() == FRAME
    assert reader.read_frame() == FRAME
    assert reader.resyncs == 0


def test_read_frame_requires_open_device() -> None:
    with pytest.raises(Ft4222Error, match="not open"):
        Ft4222Reader(FakeApi()).read_frame()


def test_misaligned_stream_resyncs_on_inter_frame_pattern() -> None:
    junk = b"\x12" * 4096  # a whole read without the sync tail
    stream = junk + b"\xff\x00" + ft.RESYNC_PATTERN + FRAME
    reader = Ft4222Reader(FakeApi(stream))
    reader.open()
    assert reader.read_frame() == FRAME
    assert (reader.resyncs, reader.reinits) == (1, 0)


def test_resync_window_finds_pattern_after_partial_match() -> None:
    # wfview's restart-at-0xFF scan can miss this; a sliding window cannot.
    stream = b"\xff\x01\xee\x01\xff" + ft.RESYNC_PATTERN
    reader = Ft4222Reader(FakeApi(stream))
    reader.open()
    assert reader.resync() is True


def test_failed_resync_reopens_device() -> None:
    api = FakeApi(b"\x00" * 4096 + b"\x00" * 64 + FRAME)
    reader = Ft4222Reader(api, max_resync_bytes=64)
    reader.open()
    assert reader.read_frame() == FRAME
    assert reader.reinits == 1
    assert names(api).count("open") == 2


def test_resync_stops_on_short_read() -> None:
    reader = Ft4222Reader(FakeApi(b""))
    reader.open()
    assert reader.resync() is False


def test_read_error_status_raises() -> None:
    api = FakeApi(FRAME)
    api.read_error_after = 0
    reader = Ft4222Reader(api)
    reader.open()
    with pytest.raises(Ft4222Error, match="SingleRead failed \\(FT_IO_ERROR\\)"):
        reader.read_frame()


# --- iteration, stop, close ----------------------------------------------------------


def test_iteration_opens_yields_and_releases_on_stop() -> None:
    api = FakeApi(FRAME * 3)
    reader = Ft4222Reader(api)
    got = []
    for frame in reader:
        got.append(frame)
        if len(got) == 2:
            reader.stop()
    assert got == [FRAME, FRAME]
    assert names(api)[-2:] == ["uninit", "close"]
    assert not reader.is_open


def test_iteration_releases_device_on_error() -> None:
    api = FakeApi(b"")
    api.read_error_after = 0
    with pytest.raises(Ft4222Error):
        list(Ft4222Reader(api))
    assert names(api)[-2:] == ["uninit", "close"]


def test_stop_from_another_thread_is_honored_by_the_reader() -> None:
    api = FakeApi(FRAME * 10_000)
    reader = Ft4222Reader(api)
    seen = threading.Event()
    released_on: list[str] = []
    original_close = api.close

    def close(handle: Any) -> int:
        released_on.append(threading.current_thread().name)
        return original_close(handle)

    api.close = close  # type: ignore[method-assign]

    def consume() -> None:
        for _ in reader:
            seen.set()

    t = threading.Thread(target=consume, name="radio-reader")
    t.start()
    assert seen.wait(2)
    reader.stop()
    t.join(2)
    assert not t.is_alive()
    assert released_on == ["radio-reader"]  # never released from the stopping thread


def test_close_is_idempotent() -> None:
    api = FakeApi()
    reader = Ft4222Reader(api)
    reader.open()
    reader.close()
    reader.close()
    assert names(api).count("close") == 1


# --- library loading and ctypes binding ------------------------------------------------


class FakeLib:
    """Stands in for a ctypes DLL: plain functions accept argtypes/restype attributes."""

    def __init__(self, functions: dict[str, Any]) -> None:
        for name, fn in functions.items():
            setattr(self, name, fn)

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)


def rec(log: list[Any], tag: str) -> Any:
    """A fake C function that logs its arguments and returns FT_OK."""

    def fn(*args: Any) -> int:
        log.append((tag, *args[1:]))
        return 0

    return fn


def d2xx_lib(log: list[Any]) -> FakeLib:
    def ft_open(desc: bytes, flags: int, handle_ptr: Any) -> int:
        log.append(("open", desc, flags))
        handle_ptr.contents.value = 1234
        return 0

    return FakeLib(
        {
            "FT_OpenEx": ft_open,
            "FT_Close": rec(log, "close"),
            "FT_SetTimeouts": rec(log, "timeouts"),
            "FT_SetLatencyTimer": rec(log, "latency"),
        }
    )


def ft4222_lib(log: list[Any]) -> FakeLib:
    def single_read(h: Any, buf: Any, size: int, got_ptr: Any, end: int) -> int:
        data = bytes(range(10))[:size]
        ctypes.memmove(buf, data, len(data))
        got_ptr.contents.value = len(data)
        log.append(("read", size, end))
        return 0

    return FakeLib(
        {
            "FT4222_UnInitialize": rec(log, "uninit"),
            "FT4222_SPIMaster_Init": rec(log, "spi_init"),
            "FT4222_SPIMaster_SingleRead": single_read,
            "FT4222_SetClock": rec(log, "clock"),
        }
    )


def test_ctypes_api_marshals_calls() -> None:
    log: list[Any] = []
    api = ft.CtypesApi(d2xx_lib(log), ft4222_lib(log))
    status, handle = api.open_ex("FT4222 A")
    assert (status, handle.value) == (0, 1234)
    results = [
        api.set_timeouts(handle, 100, 100),
        api.set_latency_timer(handle, 2),
        api.spi_master_init(handle),
        api.set_clock(handle),
        api.spi_read(handle, 4),
        api.uninitialize(handle),
        api.close(handle),
    ]
    assert results == [0, 0, 0, 0, (0, b"\x00\x01\x02\x03"), 0, 0]
    assert log[0] == ("open", b"FT4222 A", ft.FT_OPEN_BY_DESCRIPTION)
    assert ("spi_init", ft.SPI_IO_SINGLE, ft.CLK_DIV_64, ft.CLK_IDLE_HIGH, ft.CLK_LEADING, 1) in log
    assert ("clock", ft.SYS_CLK_24) in log
    assert ("read", 4, 0) in log


def test_ctypes_api_sets_signatures() -> None:
    lib = d2xx_lib([])
    ft.CtypesApi(lib, ft4222_lib([]))
    assert lib.FT_OpenEx.restype is ctypes.c_uint32
    assert len(lib.FT_OpenEx.argtypes) == 3


@pytest.mark.parametrize(
    ("is_64bit", "first"), [(True, "LibFT4222-64.dll"), (False, "LibFT4222.dll")]
)
def test_windows_library_names(is_64bit: bool, first: str) -> None:
    d2xx, ft_names = ft.library_names("win32", is_64bit)
    assert d2xx == ["ftd2xx.dll"]
    assert ft_names[0] == first
    assert len(ft_names) == 2


def test_other_platform_library_names() -> None:
    assert ft.library_names("darwin") == (["libftd2xx.dylib"], ["libft4222.dylib"])
    assert ft.library_names("linux") == ([], ["libft4222.so"])


def make_loader(available: dict[str, FakeLib], tried: list[str]) -> Any:
    def loader(path: str) -> FakeLib:
        tried.append(path)
        name = os.path.basename(path)
        if name not in available:
            raise OSError(f"{name} not found")
        return available[name]

    return loader


def test_load_api_success_with_fallback_name() -> None:
    tried: list[str] = []
    libs = {"ftd2xx.dll": d2xx_lib([]), "LibFT4222.dll": ft4222_lib([])}
    api = ft.load_api(loader=make_loader(libs, tried), platform="win32", is_64bit=True)
    assert isinstance(api, ft.CtypesApi)
    assert tried == ["ftd2xx.dll", "LibFT4222-64.dll", "LibFT4222.dll"]


def test_load_api_combined_library_on_linux() -> None:
    tried: list[str] = []
    combined = FakeLib({**vars(d2xx_lib([])), **vars(ft4222_lib([]))})
    ft.load_api(loader=make_loader({"libft4222.so": combined}, tried), platform="linux")
    assert tried == ["libft4222.so"]


def test_load_api_uses_lib_dir_and_registers_it(tmp_path: Path) -> None:
    tried: list[str] = []
    registered: list[str] = []
    libs = {"ftd2xx.dll": d2xx_lib([]), "LibFT4222-64.dll": ft4222_lib([])}
    ft.load_api(
        str(tmp_path),
        loader=make_loader(libs, tried),
        platform="win32",
        is_64bit=True,
        add_dll_directory=registered.append,
    )
    assert tried[0] == os.path.join(str(tmp_path), "ftd2xx.dll")
    assert registered == [str(tmp_path)]


def test_load_api_without_dll_directory_support(tmp_path: Path) -> None:
    libs = {"ftd2xx.dll": d2xx_lib([]), "LibFT4222-64.dll": ft4222_lib([])}
    api = ft.load_api(
        str(tmp_path),
        loader=make_loader(libs, []),
        platform="win32",
        is_64bit=True,
        add_dll_directory=None,
    )
    assert isinstance(api, ft.CtypesApi)


def test_load_api_rejects_missing_folder(tmp_path: Path) -> None:
    missing = str(tmp_path / "nope")
    with pytest.raises(LibraryNotFound, match="folder does not exist"):
        ft.load_api(missing, loader=make_loader({}, []), platform="win32")


@pytest.mark.parametrize("missing", ["ftd2xx.dll", "LibFT4222-64.dll"])
def test_load_api_reports_missing_library(missing: str) -> None:
    libs = {"ftd2xx.dll": d2xx_lib([]), "LibFT4222-64.dll": ft4222_lib([])}
    del libs[missing]
    with pytest.raises(LibraryNotFound, match=r"ftdichip\.com.*FTDI library folder"):
        ft.load_api(loader=make_loader(libs, []), platform="win32", is_64bit=True)


def test_load_api_separate_d2xx_on_macos() -> None:
    tried: list[str] = []
    libs = {"libft4222.dylib": ft4222_lib([]), "libftd2xx.dylib": d2xx_lib([])}
    ft.load_api(loader=make_loader(libs, tried), platform="darwin")
    assert tried == ["libft4222.dylib", "libftd2xx.dylib"]


def test_load_api_reports_missing_function() -> None:
    broken = FakeLib({"FT_OpenEx": d2xx_lib([]).FT_OpenEx})
    libs = {"ftd2xx.dll": broken, "LibFT4222-64.dll": ft4222_lib([])}
    with pytest.raises(LibraryNotFound, match="missing a required function"):
        ft.load_api(loader=make_loader(libs, []), platform="win32", is_64bit=True)
