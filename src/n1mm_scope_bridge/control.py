# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Optional UDP remote control (issue #30, docs/user/udp-control.md).

Off by default. When enabled it listens on 127.0.0.1 only, unless the operator
sets another bind address *and* an allow-list of client IPs. Requests from
any other address are ignored. One UTF-8 command per datagram; each reply is
one line of JSON sent back to the requester.

Safety: no command transmits, keys the radio, or changes radio state. The
commands only start or stop streaming to N1MM+ and change how it is sent.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import socket
import threading
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from n1mm_scope_bridge import __version__
from n1mm_scope_bridge.bridge import COMBINE_MODES

DEFAULT_CONTROL_PORT = 13070
DEFAULT_CONTROL_BIND = "127.0.0.1"
MAX_REQUEST = 512
LOOPBACK = ("127.0.0.1", "::1")
SETTABLE = ("name", "rate", "combine", "scaling")
HELP = (
    "commands: status | start | stop | ping | help | "
    "set name <text> | set rate <1-10> | set combine latest|average|peak | set scaling <x>"
)


class BridgeController(Protocol):
    """What a running bridge (CLI or GUI) exposes to remote control."""

    def status(self) -> dict[str, Any]:
        """Current state as JSON-safe values (``streaming``, ``radio``, stats, ...)."""

    def start(self) -> None:
        """Start streaming to N1MM+ (no-op if already streaming)."""

    def stop(self) -> None:
        """Stop streaming to N1MM+ (the program keeps running)."""

    def set_option(self, name: str, value: str | float) -> None:
        """Change ``name``, ``rate``, ``combine``, or ``scaling``; raise ValueError if invalid."""


def _parse_set(args: list[str]) -> tuple[str, str | float]:
    if len(args) < 2:
        raise ValueError("usage: set name|rate|combine|scaling <value>")
    option, raw = args[0].lower(), " ".join(args[1:])
    if option not in SETTABLE:
        raise ValueError(f"cannot set {option!r}; settable: {', '.join(SETTABLE)}")
    if option == "combine":
        if raw.lower() not in COMBINE_MODES:
            raise ValueError(f"combine must be one of {', '.join(COMBINE_MODES)}")
        return option, raw.lower()
    if option == "name":
        return option, raw
    try:
        return option, float(raw)
    except ValueError:
        raise ValueError(f"{option} must be a number") from None


def _set(controller: BridgeController, args: list[str]) -> dict[str, Any]:
    option, value = _parse_set(args)
    controller.set_option(option, value)
    return {option: value}


def _start(controller: BridgeController, args: list[str]) -> dict[str, Any]:
    controller.start()
    return controller.status()


def _stop(controller: BridgeController, args: list[str]) -> dict[str, Any]:
    controller.stop()
    return controller.status()


COMMANDS: dict[str, Callable[[BridgeController, list[str]], dict[str, Any]]] = {
    "ping": lambda c, a: {"version": __version__},
    "help": lambda c, a: {"help": HELP},
    "status": lambda c, a: c.status(),
    "start": _start,
    "stop": _stop,
    "set": _set,
}


def handle_command(text: str, controller: BridgeController) -> dict[str, Any]:
    """Run one command and return the JSON-able reply (never raises)."""
    words = text.strip().split()
    if not words:
        return {"ok": False, "error": "empty command; try 'help'"}
    action = COMMANDS.get(words[0].lower())
    if action is None:
        return {"ok": False, "error": f"unknown command {words[0]!r}; try 'help'"}
    try:
        return {"ok": True, **action(controller, words[1:])}
    except (ValueError, OSError) as err:
        return {"ok": False, "error": str(err)}


def is_loopback(address: str) -> bool:
    return ipaddress.ip_address(address).is_loopback


def parse_allow(text: str) -> tuple[str, ...]:
    """Comma- or space-separated client IPs; raises ValueError on a bad entry."""
    entries = [e for e in text.replace(",", " ").split() if e]
    return tuple(str(ipaddress.ip_address(e)) for e in entries)


class ControlServer:
    """UDP command listener on its own thread (named ``control``)."""

    def __init__(
        self,
        controller: BridgeController,
        *,
        port: int = DEFAULT_CONTROL_PORT,
        bind: str = DEFAULT_CONTROL_BIND,
        allow: Iterable[str] = (),
        log: Callable[[str], object] = lambda _: None,
    ) -> None:
        bind_ip = ipaddress.ip_address(bind)
        allowed = set(allow)
        if not bind_ip.is_loopback and not allowed:
            raise ValueError("a non-loopback control address needs an allow-list of client IPs")
        self._allowed = allowed | set(LOOPBACK) if bind_ip.is_loopback else allowed
        family = socket.AF_INET6 if bind_ip.version == 6 else socket.AF_INET
        self._sock = socket.socket(family, socket.SOCK_DGRAM)
        self._sock.bind((bind, port))
        self._sock.settimeout(0.2)
        self.address: tuple[str, int] = self._sock.getsockname()[:2]
        self._controller = controller
        self._log = log
        self._stop = threading.Event()
        self.ignored = 0
        self._thread = threading.Thread(target=self._serve, name="control")

    def start(self) -> ControlServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        self._sock.close()

    def __enter__(self) -> ControlServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                data, peer = self._sock.recvfrom(MAX_REQUEST + 1)
            except OSError:  # timeout, or closed during shutdown
                continue
            if peer[0] not in self._allowed:
                self.ignored += 1
                continue
            if len(data) > MAX_REQUEST:
                reply: dict[str, Any] = {"ok": False, "error": "command too long"}
            else:
                reply = handle_command(data.decode("utf-8", "replace"), self._controller)
            self._log(f"control: {data[:60]!r} from {peer[0]} -> ok={reply['ok']}")
            with contextlib.suppress(OSError):
                self._sock.sendto(json.dumps(reply).encode("utf-8"), peer)


def request(command: str, *, host: str = "127.0.0.1", port: int = DEFAULT_CONTROL_PORT,
            timeout: float = 2.0) -> dict[str, Any]:  # fmt: skip
    """Send one command and return the parsed reply; raises TimeoutError if none."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(command.encode("utf-8"), (host, port))
        data, _ = sock.recvfrom(65535)
    reply: dict[str, Any] = json.loads(data)
    return reply
