# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""dev_cat.py: whitelisted bench CAT helper. Uses fake ports only, never real devices."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import dev_cat as dc
import pytest

from n1mm_scope_bridge.emulator import Ft710Emulator

ROOT = Path(__file__).resolve().parents[2]


class ScriptedPort:
    """Replies to each write with the next scripted reply; records everything written."""

    def __init__(self, replies: dict[str, list[str]] | None = None) -> None:
        self.replies = {k: list(v) for k, v in (replies or {}).items()}
        self.writes: list[str] = []
        self.buffer = b""
        self.closed = False

    def write(self, data: bytes, /) -> int:
        cmd = data.decode()
        self.writes.append(cmd)
        if self.replies.get(cmd):
            self.buffer += self.replies[cmd].pop(0).encode()
        return len(data)

    def read_until(self, expected: bytes = b";", size: int | None = None) -> bytes:
        end = self.buffer.find(expected)
        if end < 0:
            out, self.buffer = self.buffer, b""
            return out
        out, self.buffer = self.buffer[: end + 1], self.buffer[end + 1 :]
        return out

    def reset_input_buffer(self) -> None:
        pass  # keep scripted replies; a real port would drop stale bytes

    def close(self) -> None:
        self.closed = True


def emu_cat() -> tuple[dc.DevCat, Ft710Emulator, dc.EmulatorCatPort]:
    emu = Ft710Emulator()
    port = dc.EmulatorCatPort(emu)
    return dc.DevCat(port, sleep=lambda _: None), emu, port


@pytest.mark.parametrize("cmd", ["FA;", "SS05;", "SS06;", "SS0560000;", "SS06A0000;", "SS0600000;"])
def test_whitelist_allows(cmd: str) -> None:
    assert dc.check_command(cmd) == cmd


@pytest.mark.parametrize(
    "cmd",
    ["TX1;", "TX;", "FA014074000;", "MD02;", "EX0101;", "SS0700000;", "SS05A0000;",
     "SS0661234;", "ss05;", "FA", "PC100;", "SS06B0000;", ""],
)  # fmt: skip
def test_whitelist_refuses_everything_else(cmd: str) -> None:
    with pytest.raises(dc.CatError, match="refusing"):
        dc.check_command(cmd)


def test_refused_command_is_never_written() -> None:
    port = ScriptedPort()
    cat = dc.DevCat(port, sleep=lambda _: None)
    with pytest.raises(dc.CatError):
        cat._transact("TX1;", "TX")
    assert port.writes == []


def test_command_builders() -> None:
    assert dc.span_command(6) == "SS0560000;"
    assert dc.mode_command("A") == "SS06A0000;"
    with pytest.raises(dc.CatError):
        dc.span_command(10)
    with pytest.raises(dc.CatError):
        dc.mode_command("B")


def test_reads_against_the_emulator() -> None:
    cat, emu, _ = emu_cat()
    emu.tune(7_074_000)
    assert cat.read_vfo_a_hz() == 7_074_000
    assert cat.read_span_index() == emu.state.span_index
    assert cat.read_scope_mode() == "4"


def test_sets_change_the_emulator_and_are_verified() -> None:
    cat, emu, port = emu_cat()
    cat.set_span_index(9)
    cat.set_scope_mode("A")
    assert (emu.state.span_index, emu.state.scope_mode) == (9, 0x0A)
    assert "SS0590000;" in port.writes
    assert "SS06A0000;" in port.writes


def test_set_that_does_not_stick_raises() -> None:
    port = ScriptedPort({"SS05;": ["SS0530000;"]})
    cat = dc.DevCat(port, sleep=lambda _: None)
    with pytest.raises(dc.CatError, match="did not change"):
        cat.set_span_index(6)


def test_skips_unsolicited_lines_and_handles_errors() -> None:
    port = ScriptedPort({"FA;": ["IF00014074000;FA014074000;"], "SS05;": ["?;"], "SS06;": []})
    cat = dc.DevCat(port, sleep=lambda _: None)
    assert cat.read_vfo_a_hz() == 14_074_000
    with pytest.raises(dc.CatError, match="rejected"):
        cat.read_span_index()
    with pytest.raises(dc.CatError, match="timeout"):
        cat.read_scope_mode()


@pytest.mark.parametrize(
    ("replies", "call", "message"),
    [
        ({"FA;": ["FAabc;"]}, "read_vfo_a_hz", "unexpected FA"),
        ({"SS05;": ["SS05;"]}, "read_span_index", "unexpected SS05"),
        ({"SS06;": ["SS06Z;"]}, "read_scope_mode", "unexpected SS06"),
        ({"FA;": ["XX1;" * 9]}, "read_vfo_a_hz", "no FA reply"),
    ],
)
def test_bad_replies(replies: dict[str, list[str]], call: str, message: str) -> None:
    cat = dc.DevCat(ScriptedPort(replies), sleep=lambda _: None)
    with pytest.raises(dc.CatError, match=message):
        getattr(cat, call)()


def test_restorer_restores_after_success_and_after_errors() -> None:
    cat, emu, _ = emu_cat()
    emu.set_span(3)
    emu.set_scope_mode(0x07)
    with dc.ScopeRestorer(cat) as original:
        cat.set_span_index(9)
        cat.set_scope_mode("4")
    assert (original.span_index, original.mode) == (3, "7")
    assert (emu.state.span_index, emu.state.scope_mode) == (3, 0x07)

    def interrupted() -> None:
        with dc.ScopeRestorer(cat):
            cat.set_span_index(0)
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        interrupted()
    assert emu.state.span_index == 3


def test_restorer_reports_a_failed_restore(capsys: pytest.CaptureFixture[str]) -> None:
    cat, emu, _ = emu_cat()

    class Stuck(dc.EmulatorCatPort):
        def write(self, data: bytes, /) -> int:
            if data.startswith(b"SS05") and len(data) > 5:
                return len(data)  # the radio ignores span sets
            return super().write(data)

    stuck = dc.DevCat(Stuck(emu), sleep=lambda _: None)
    emu.set_span(2)
    with pytest.raises(dc.CatError, match="could not restore"), dc.ScopeRestorer(stuck):
        emu.set_span(5)

    def failing_capture() -> None:
        with dc.ScopeRestorer(stuck):
            emu.set_span(6)
            raise RuntimeError("capture failed")

    with pytest.raises(RuntimeError):
        failing_capture()
    assert "warning: could not restore" in capsys.readouterr().err
    assert cat.read_span_index() == 6


class FakeSerial:
    instances: ClassVar[list[FakeSerial]] = []

    def __init__(self) -> None:
        self.attrs: dict[str, Any] = {}
        self.opened_with: dict[str, Any] = {}
        self.port_impl = ScriptedPort()
        FakeSerial.instances.append(self)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("attrs", "opened_with", "port_impl"):
            object.__setattr__(self, name, value)
        else:
            self.attrs[name] = value

    def open(self) -> None:
        self.opened_with = dict(self.attrs)
        if self.attrs["baudrate"] == 38400:
            self.port_impl.replies = {"FA;": ["FA014074000;"]}

    def write(self, data: bytes, /) -> int:
        return self.port_impl.write(data)

    def read_until(self, expected: bytes = b";", size: int | None = None) -> bytes:
        return self.port_impl.read_until(expected, size)

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.port_impl.closed = True


def test_open_serial_holds_rts_and_dtr_low_before_opening() -> None:
    FakeSerial.instances.clear()
    dc.open_serial("/dev/fake", 38400, serial_factory=FakeSerial)
    opened = FakeSerial.instances[0].opened_with
    assert opened["rts"] is False
    assert opened["dtr"] is False
    assert opened["rtscts"] is False
    assert opened["dsrdtr"] is False
    assert opened["timeout"] == dc.TIMEOUT_S


def test_connect_finds_the_baud_rate_read_only() -> None:
    FakeSerial.instances.clear()
    cat, baud = dc.connect("/dev/fake", bauds=(4800, 38400), serial_factory=FakeSerial)
    assert baud == 38400
    assert FakeSerial.instances[0].port_impl.closed
    assert all(w == "FA;" for f in FakeSerial.instances for w in f.port_impl.writes)
    with pytest.raises(dc.CatError, match="no FT-710 CAT reply"):
        dc.connect("/dev/fake", bauds=(4800,), serial_factory=FakeSerial)
    cat.close()


def test_package_never_imports_dev_cat() -> None:
    for path in (ROOT / "src").rglob("*.py"):
        assert "dev_cat" not in path.read_text(encoding="utf-8"), path
