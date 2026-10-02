# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Minimal, whitelisted Yaesu FT-710 CAT client for DEVELOPMENT tooling only.

Used by ``capture_golden.py --auto`` and ``hardware_smoke.py`` to read the
radio's VFO-A frequency and to set the spectrum scope span and mode while
recording golden captures. It is never imported by the bridge package: the
shipped bridge never opens the radio's COM ports (N1MM+ owns them).

Safety rules enforced here:
- Only the commands in ``READS`` may be sent as queries, and only scope span
  (``SS05``) and scope mode (``SS06``) may be set. Anything else raises
  ``CatError`` before a byte is written. No transmit, PTT, frequency, mode, or
  menu command can be sent.
- The port is opened with RTS and DTR held low and no hardware flow control,
  so opening it can never key PTT or CW through modem-control lines.
- ``ScopeRestorer`` records the original span and mode first and always puts
  them back (``with`` block, including on errors and Ctrl-C).

Command formats follow wfview's rigs/FT-710.rig (Scope Span ``SS05`` and Scope
Mode ``SS06``, 5 parameter bytes, left-justified, padded with ``0``) and
src/radio/yaesucommander.cpp. UNVERIFIED (#36): the FT-710's exact reply
format for SS05/SS06 reads; every change is therefore also confirmed from the
scope stream itself.
"""

from __future__ import annotations

import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol

READS = ("FA;", "SS05;", "SS06;")
SET_PATTERN = re.compile(r"^SS0(?:(5)([0-9])|(6)([0-9A]))0000;$")
"""Scope span (SS05, index 0-9) or scope mode (SS06, code 0-A) sets; nothing else."""
SPAN_COUNT = 10
SCOPE_MODES = "0123456789A"
BAUD_RATES = (38400, 4800, 9600, 19200, 115200)
TIMEOUT_S = 0.5
MAX_REPLY = 64


class CatError(RuntimeError):
    """A CAT command was refused, timed out, or got an unexpected reply."""


class SerialLike(Protocol):
    def write(self, data: bytes, /) -> int | None:
        """Send bytes to the radio."""

    def read_until(self, expected: bytes = b";", size: int | None = None) -> bytes:
        """Read up to and including ``expected`` (or until the timeout)."""

    def reset_input_buffer(self) -> None:
        """Drop unread input."""

    def close(self) -> None:
        """Release the port."""


def check_command(cmd: str) -> str:
    """Return ``cmd`` if it is on the whitelist, otherwise raise ``CatError``."""
    if cmd in READS or SET_PATTERN.match(cmd):
        return cmd
    raise CatError(f"refusing CAT command {cmd!r}: not on the dev_cat whitelist")


def span_command(index: int) -> str:
    if not 0 <= index < SPAN_COUNT:
        raise CatError(f"span index {index} is outside 0..{SPAN_COUNT - 1}")
    return f"SS05{index}0000;"


def mode_command(code: str) -> str:
    if len(code) != 1 or code not in SCOPE_MODES:
        raise CatError(f"scope mode {code!r} is not one of {SCOPE_MODES}")
    return f"SS06{code}0000;"


class DevCat:
    """Talks to the radio through any ``SerialLike`` (a real port or a test fake)."""

    def __init__(self, port: SerialLike, *, sleep: Callable[[float], object] = time.sleep) -> None:
        self._port = port
        self._sleep = sleep

    def _transact(self, cmd: str, reply_prefix: str) -> str:
        self._port.reset_input_buffer()
        self._port.write(check_command(cmd).encode("ascii"))
        # Skip unsolicited auto-information lines until the reply we asked for.
        for _ in range(8):
            raw = self._port.read_until(b";", MAX_REPLY)
            if not raw.endswith(b";"):
                raise CatError(f"no reply to {cmd!r} (timeout)")
            text = raw.decode("ascii", "replace").strip()
            if text == "?;":
                raise CatError(f"radio rejected {cmd!r}")
            if text.startswith(reply_prefix):
                return text[len(reply_prefix) : -1]
        raise CatError(f"no {reply_prefix} reply to {cmd!r}")

    def read_vfo_a_hz(self) -> int:
        digits = self._transact("FA;", "FA")
        if not digits.isdigit():
            raise CatError(f"unexpected FA reply {digits!r}")
        return int(digits)

    def read_span_index(self) -> int:
        param = self._transact("SS05;", "SS05")
        if not param or not param[0].isdigit():
            raise CatError(f"unexpected SS05 reply {param!r}")
        return int(param[0])

    def read_scope_mode(self) -> str:
        param = self._transact("SS06;", "SS06")
        if not param or param[0] not in SCOPE_MODES:
            raise CatError(f"unexpected SS06 reply {param!r}")
        return param[0]

    def _set(self, cmd: str) -> None:
        self._port.reset_input_buffer()
        self._port.write(check_command(cmd).encode("ascii"))
        self._sleep(0.15)  # Yaesu sets don't answer; give the radio time to apply

    def set_span_index(self, index: int) -> None:
        self._set(span_command(index))
        if self.read_span_index() != index:
            raise CatError(f"span did not change to index {index}")

    def set_scope_mode(self, code: str) -> None:
        self._set(mode_command(code))
        if self.read_scope_mode() != code:
            raise CatError(f"scope mode did not change to {code!r}")

    def close(self) -> None:
        self._port.close()


@dataclass
class ScopeRestorer:
    """Records the scope span and mode on entry and always restores them on exit."""

    cat: DevCat
    span_index: int = -1
    mode: str = ""

    def __enter__(self) -> ScopeRestorer:
        self.span_index = self.cat.read_span_index()
        self.mode = self.cat.read_scope_mode()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # Restore even after errors or Ctrl-C; try both even if one fails.
        errors: list[str] = []
        try:
            self.cat.set_scope_mode(self.mode)
        except CatError as err:
            errors.append(str(err))
        try:
            self.cat.set_span_index(self.span_index)
        except CatError as err:
            errors.append(str(err))
        if errors:
            message = "could not restore the scope: " + "; ".join(errors)
            if exc_type is None:
                raise CatError(message)
            print(f"warning: {message}", file=sys.stderr)


SerialFactory = Callable[..., Any]


def open_serial(
    device: str, baud: int, *, serial_factory: SerialFactory | None = None
) -> SerialLike:
    """Open a CAT port with RTS/DTR low and no flow control (never keys the radio)."""
    if serial_factory is None:  # pragma: no cover - needs pyserial (dev group "hardware")
        import serial  # type: ignore[import-untyped,unused-ignore]  # noqa: PLC0415

        serial_factory = serial.Serial
    port = serial_factory()
    port.port = device
    port.baudrate = baud
    port.timeout = TIMEOUT_S
    port.write_timeout = TIMEOUT_S
    port.rtscts = False
    port.dsrdtr = False
    port.xonxoff = False
    port.rts = False  # applied when the port opens: PTT/keying lines stay low
    port.dtr = False
    port.open()
    return port  # type: ignore[no-any-return]


def connect(
    device: str,
    *,
    bauds: Sequence[int] = BAUD_RATES,
    serial_factory: SerialFactory | None = None,
    sleep: Callable[[float], object] = time.sleep,
) -> tuple[DevCat, int]:
    """Find the radio's CAT baud rate with a read-only ``FA;`` query."""
    tried = []
    for baud in bauds:
        port = open_serial(device, baud, serial_factory=serial_factory)
        cat = DevCat(port, sleep=sleep)
        try:
            cat.read_vfo_a_hz()
        except CatError:
            cat.close()
            tried.append(str(baud))
            continue
        return cat, baud
    raise CatError(f"no FT-710 CAT reply on {device} at {', '.join(tried)} baud")


class EmulatorCatPort:
    """A ``SerialLike`` CAT port backed by the FT-710 emulator (dry runs and tests).

    Applies whitelisted SS05/SS06 sets to the emulator's radio state and answers
    FA/SS05/SS06 reads from it, so ``--auto --dry-run`` exercises the whole flow.
    """

    def __init__(self, emulator: Any) -> None:
        self._emu = emulator
        self._out = b""
        self.writes: list[str] = []
        self.closed = False

    def write(self, data: bytes, /) -> int:
        cmd = check_command(data.decode("ascii"))
        self.writes.append(cmd)
        state = self._emu.state
        if cmd == "FA;":
            self._out += f"FA{state.vfo_a_hz:09d};".encode()
        elif cmd == "SS05;":
            self._out += f"SS05{state.span_index}0000;".encode()
        elif cmd == "SS06;":
            self._out += f"SS06{state.scope_mode:X}0000;".encode()
        else:
            match = SET_PATTERN.match(cmd)
            assert match is not None  # check_command guarantees it
            span, mode = match.group(2), match.group(4)
            if span is not None:
                self._emu.set_span(int(span))
            else:
                self._emu.set_scope_mode(int(mode, 16))
        return len(data)

    def read_until(self, expected: bytes = b";", size: int | None = None) -> bytes:
        end = self._out.find(expected)
        if end < 0:
            return b""
        reply, self._out = self._out[: end + 1], self._out[end + 1 :]
        return reply

    def reset_input_buffer(self) -> None:
        self._out = b""

    def close(self) -> None:
        self.closed = True
