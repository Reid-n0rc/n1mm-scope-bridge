# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import ctypes
import os
import threading
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeApi
from frames import make_ft4222_frame

from n1mm_scope_bridge.transport import ft4222 as ft
from n1mm_scope_bridge.transport.ft4222 import (
    DeviceNotFound,
    Ft4222Error,
    Ft4222Reader,
    LibraryNotFound,
)

FRAME = make_ft4222_frame()


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
    api: FakeApi = FakeApi(b"", **{step: 4})  # type: ignore[arg-type]
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


def test_resync_skips_sync_padding_and_returns_next_frame_start() -> None:
    stream = b"\x00\xff\x01" + ft.RESYNC_PATTERN + b"\xff\x01\xee\x01" + b"NEXT"
    reader = Ft4222Reader(FakeApi(stream))
    reader.open()
    assert reader.resync() == b"NEXT"


def test_resync_handles_unpadded_frames() -> None:
    # Frames back to back with zero padding: a single sync marks the boundary.
    stream = FRAME[100:] + FRAME + FRAME
    reader = Ft4222Reader(FakeApi(stream))
    reader.open()
    assert reader.read_frame() == FRAME
    assert reader.resyncs == 1


@pytest.mark.parametrize("cut", [b"", b"\xff\x01\xee\x01\xff\x01"])
def test_resync_stream_ends_inside_padding(cut: bytes) -> None:
    reader = Ft4222Reader(FakeApi(b"\x00\xff\x01\xee\x01" + cut))
    reader.open()
    assert reader.resync() is None


def test_resync_gives_up_on_endless_padding() -> None:
    reader = Ft4222Reader(FakeApi(ft.RESYNC_PATTERN * 25), max_resync_bytes=32)
    reader.open()
    assert reader.resync() is None


def test_failed_resync_reopens_device() -> None:
    api = FakeApi(b"\x00" * 4096 + b"\x00" * 64 + FRAME)
    reader = Ft4222Reader(api, max_resync_bytes=64)
    reader.open()
    assert reader.read_frame() == FRAME
    assert reader.reinits == 1
    assert names(api).count("open") == 2


def test_silent_device_gives_up_after_max_reinits() -> None:
    api = FakeApi(b"")  # opens fine but never produces data
    reader = Ft4222Reader(api)
    reader.open()
    with pytest.raises(Ft4222Error, match="No valid scope frames"):
        reader.read_frame()
    assert reader.reinits == ft.MAX_REINITS


def test_stop_during_recovery_returns_none() -> None:
    reader = Ft4222Reader(FakeApi(b""))
    original_open = reader.open
    opens = []

    def open_then_stop_on_reinit() -> None:
        original_open()
        opens.append(1)
        if len(opens) > 1:
            reader.stop()

    reader.open = open_then_stop_on_reinit  # type: ignore[method-assign]
    assert list(reader) == []  # iteration ends cleanly instead of spinning
    assert len(opens) == 2
    assert not reader.is_open


def test_garbled_stream_that_keeps_resyncing_gives_up() -> None:
    # Sync markers everywhere but never a whole valid frame.
    garbage = (b"\x00" * 100 + ft.RESYNC_PATTERN[:4] + b"\x11" * 4) * 5000
    reader = Ft4222Reader(FakeApi(repeat=garbage))
    reader.open()
    with pytest.raises(Ft4222Error, match="No valid scope frames"):
        reader.read_frame()
    assert reader.resyncs >= ft.MAX_RESYNCS
    assert reader.reinits == ft.MAX_REINITS


def test_resync_stops_on_short_read() -> None:
    reader = Ft4222Reader(FakeApi(b""))
    reader.open()
    assert reader.resync() is None


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


# --- packaged app: DLLs installed next to the exe (#133) -----------------------------------


def test_app_folder_with_ftdi(tmp_path: Path) -> None:
    exe = tmp_path / "n1mm-scope-bridge.exe"
    exe.write_bytes(b"")
    assert ft.app_folder_with_ftdi("win32", frozen=True, executable=str(exe)) is None
    (tmp_path / "LibFT4222-64.dll").write_bytes(b"")
    assert ft.app_folder_with_ftdi("win32", frozen=True, executable=str(exe)) == str(tmp_path)
    assert ft.app_folder_with_ftdi("win32", frozen=False, executable=str(exe)) is None
    assert ft.app_folder_with_ftdi("darwin", frozen=True, executable=str(exe)) is None
    assert ft.app_folder_with_ftdi() is None  # tests never run frozen


def test_load_api_prefers_frozen_app_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tried: list[str] = []
    registered: list[str] = []
    libs = {"ftd2xx.dll": d2xx_lib([]), "LibFT4222-64.dll": ft4222_lib([])}
    monkeypatch.setattr(ft, "app_folder_with_ftdi", lambda platform: str(tmp_path))
    ft.load_api(
        loader=make_loader(libs, tried),
        platform="win32",
        is_64bit=True,
        add_dll_directory=registered.append,
    )
    assert registered == [str(tmp_path)]
    assert tried[0] == os.path.join(str(tmp_path), "ftd2xx.dll")


# --- FTDI package layout and architecture checks (#146) -------------------------------------


def write_pe(path: Path, machine: int) -> Path:
    """A minimal PE header: MZ stub pointing at 'PE\\0\\0' + the machine field."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stub = bytearray(64)
    stub[:2] = b"MZ"
    stub[0x3C:0x40] = (64).to_bytes(4, "little")
    path.write_bytes(bytes(stub) + b"PE\0\0" + machine.to_bytes(2, "little"))
    return path


X64, ARM64, X86 = 0x8664, 0xAA64, 0x014C


def ftdi_package(
    root: Path, machine: int = X64, sub: str = "amd64", d2xx: str = "ftd2xx.dll"
) -> Path:
    write_pe(root / "imports" / "LibFT4222" / "dll" / sub / "LibFT4222-64.dll", machine)
    write_pe(root / "imports" / "ftd2xx" / "dll" / sub / d2xx, machine)
    return root


def path_loader(available: dict[str, FakeLib], tried: list[str]) -> Any:
    def loader(path: str) -> FakeLib:
        tried.append(path)
        if not os.path.isfile(path):
            raise OSError(f"{path} not found")
        return available[os.path.basename(path)]

    return loader


LIBS = {
    "ftd2xx.dll": d2xx_lib([]),
    "ftd2xx64.dll": d2xx_lib([]),
    "LibFT4222-64.dll": ft4222_lib([]),
}


@pytest.mark.parametrize(
    "chosen",
    [
        "",  # the package root
        "imports",
        "imports/LibFT4222/dll/amd64",  # the folder the user picked in #146
        "imports/ftd2xx/dll/amd64",
    ],
)
def test_load_api_finds_both_dlls_in_an_ftdi_package(tmp_path: Path, chosen: str) -> None:
    root = ftdi_package(tmp_path / "LibFT4222-v1.4.8")
    tried: list[str] = []
    registered: list[str] = []
    api = ft.load_api(
        str(root / chosen) if chosen else str(root),
        loader=path_loader(LIBS, tried),
        platform="win32",
        add_dll_directory=registered.append,
        arch="x64",
    )
    assert isinstance(api, ft.CtypesApi)
    assert tried[0].endswith(os.path.join("ftd2xx", "dll", "amd64", "ftd2xx.dll"))
    assert tried[1].endswith(os.path.join("LibFT4222", "dll", "amd64", "LibFT4222-64.dll"))
    # ftd2xx's folder is registered so LibFT4222 can resolve its dependency.
    assert str(root / "imports" / "ftd2xx" / "dll" / "amd64") in registered


def test_load_api_accepts_ftd2xx64_name(tmp_path: Path) -> None:
    root = ftdi_package(tmp_path, d2xx="ftd2xx64.dll")
    api = ft.load_api(
        str(root),
        loader=path_loader(LIBS, []),
        platform="win32",
        add_dll_directory=None,
        arch="x64",
    )
    assert isinstance(api, ft.CtypesApi)


def test_arm64_dlls_in_x64_app_give_a_clear_error(tmp_path: Path) -> None:
    # #146: the user picked dll\arm64 while the app runs as x64.
    arm = ftdi_package(tmp_path / "pkg", machine=ARM64, sub="arm64")
    chosen = arm / "imports" / "LibFT4222" / "dll" / "arm64"
    with pytest.raises(LibraryNotFound, match=r"built for ARM64 .*runs as x64.*amd64 DLLs"):
        ft.load_api(str(chosen), loader=path_loader(LIBS, []), platform="win32", arch="x64")


def test_package_with_both_arches_picks_the_right_one(tmp_path: Path) -> None:
    root = ftdi_package(tmp_path, machine=X64, sub="amd64")
    ftdi_package(tmp_path, machine=ARM64, sub="arm64")
    tried: list[str] = []
    ft.load_api(
        str(root / "imports" / "LibFT4222" / "dll" / "arm64"),
        loader=path_loader(LIBS, tried),
        platform="win32",
        add_dll_directory=None,
        arch="x64",
    )
    assert all("amd64" in p for p in tried)


def test_missing_ftd2xx_is_named_in_the_error(tmp_path: Path) -> None:
    write_pe(tmp_path / "LibFT4222-64.dll", X64)
    with pytest.raises(LibraryNotFound, match=r"missing: ftd2xx\.dll; tried:"):
        ft.load_api(
            str(tmp_path),
            loader=path_loader(LIBS, []),
            platform="win32",
            add_dll_directory=None,
            arch="x64",
        )


def test_bad_exe_format_from_loader_is_an_arch_error(tmp_path: Path) -> None:
    write_pe(tmp_path / "ftd2xx.dll", X64)
    write_pe(tmp_path / "LibFT4222-64.dll", X64)

    def loader(path: str) -> FakeLib:
        err = OSError("not a valid Win32 application")
        err.winerror = 193  # type: ignore[attr-defined,unused-ignore]  # only typed on Windows
        raise err

    with pytest.raises(LibraryNotFound, match="runs as x64"):
        ft.load_api(
            str(tmp_path), loader=loader, platform="win32", add_dll_directory=None, arch="x64"
        )


def test_other_load_failure_falls_back_and_reports(tmp_path: Path) -> None:
    write_pe(tmp_path / "ftd2xx.dll", X64)
    write_pe(tmp_path / "LibFT4222-64.dll", X64)

    def loader(path: str) -> FakeLib:
        raise OSError("access denied")

    with pytest.raises(LibraryNotFound, match="Could not load FTDI"):
        ft.load_api(
            str(tmp_path), loader=loader, platform="win32", add_dll_directory=None, arch="x64"
        )


@pytest.mark.parametrize(
    ("tag", "arch"),
    [("win-amd64", "x64"), ("win-arm64", "ARM64"), ("win32", "x86"), ("linux-x86_64", "x64")],
)
def test_process_arch(tag: str, arch: str) -> None:
    assert ft.process_arch(tag) == arch
    assert ft.process_arch() in {"x64", "x86", "ARM64"}


def test_pe_machine(tmp_path: Path) -> None:
    assert ft.pe_machine(str(write_pe(tmp_path / "a.dll", ARM64))) == "ARM64"
    assert ft.pe_machine(str(write_pe(tmp_path / "b.dll", X86))) == "x86"
    assert ft.pe_machine(str(write_pe(tmp_path / "c.dll", 0x1234))) == "0x1234"
    (tmp_path / "d.dll").write_bytes(b"not a pe")
    assert ft.pe_machine(str(tmp_path / "d.dll")) is None
    bad = bytearray(64)
    bad[:2] = b"MZ"
    bad[0x3C:0x40] = (64).to_bytes(4, "little")
    (tmp_path / "e.dll").write_bytes(bytes(bad) + b"XX\0\0\0\0")
    assert ft.pe_machine(str(tmp_path / "e.dll")) is None
    assert ft.pe_machine(str(tmp_path / "missing.dll")) is None


def test_ftdi_package_root(tmp_path: Path) -> None:
    root = ftdi_package(tmp_path / "pkg")
    deep = root / "imports" / "LibFT4222" / "dll" / "amd64"
    assert ft.ftdi_package_root(str(deep)) == str(root)
    assert ft.ftdi_package_root(str(root)) == str(root)
    assert ft.ftdi_package_root(str(tmp_path / "pkg" / "imports")) == str(root)
    lone = tmp_path / "elsewhere"
    lone.mkdir()
    assert ft.ftdi_package_root(str(lone), max_up=1) is None
    assert ft.ftdi_package_root(os.path.abspath(os.sep)) is None


# --- path normalization (#146 follow-up) ------------------------------------------------------


def test_normalize_dir_expands_home_and_native_separators(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert ft.normalize_dir("") == ""
    assert ft.normalize_dir(None) == ""
    assert ft.normalize_dir("  ") == ""
    got = ft.normalize_dir("~/Downloads/LibFT4222-v1.4.8/imports//LibFT4222/dll/./amd64/ ")
    assert got == os.path.join(
        str(tmp_path), "Downloads", "LibFT4222-v1.4.8", "imports", "LibFT4222", "dll", "amd64"
    )
    assert "~" not in got


def test_load_api_expands_user_typed_home_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    ftdi_package(tmp_path / "Downloads" / "LibFT4222-v1.4.8")
    tried: list[str] = []
    ft.load_api(
        "~/Downloads/LibFT4222-v1.4.8/imports/LibFT4222/dll/amd64",
        loader=path_loader(LIBS, tried),
        platform="win32",
        add_dll_directory=None,
        arch="x64",
    )
    assert all(p.startswith(str(tmp_path)) and "~" not in p for p in tried)
    assert all(os.path.normpath(p) == p for p in tried)  # consistent separators in messages
