# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""N1MM Logger+ external spectrum packet: encoder and UDP sender.

Source: N1MM+ manual, External UDP Messages,
https://n1mmwp.hamdocs.com/appendices/external-udp-broadcasts/ (element names,
order, and port only; no code copied). See docs/n1mm-spectrum-protocol.md.
"""

from __future__ import annotations

import math
import re
import socket
from collections.abc import Callable
from typing import Any, Protocol
from xml.sax.saxutils import escape

from n1mm_scope_bridge.spectrum import SpectrumFrame

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 13064
DEFAULT_APP = "n1mm-scope-bridge"

#: Largest UDP payload over IPv4.
MAX_DATAGRAM = 65507

# XML 1.0 forbids most C0 control characters, and N1MM shows the name in its UI.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_XML_ATTR_ENTITIES = {'"': "&quot;", "'": "&apos;"}


def format_khz(hz: int) -> str:
    """Format a frequency in Hz as kHz with up to 3 decimals and no trailing zeros.

    >>> format_khz(14074000), format_khz(14074500), format_khz(7000001)
    ('14074', '14074.5', '7000.001')
    """
    if hz < 0:
        raise ValueError(f"frequency must be >= 0 Hz, got {hz}")
    whole, frac = divmod(hz, 1000)
    if frac == 0:
        return str(whole)
    return f"{whole}.{frac:03d}".rstrip("0")


def _text(value: str, field: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field} must not be empty")
    if _CONTROL.search(value):
        raise ValueError(f"{field} must not contain control characters")
    return escape(value, _XML_ATTR_ENTITIES)


def encode_spectrum(
    frame: SpectrumFrame,
    *,
    name: str,
    scaling: float,
    app: str = DEFAULT_APP,
) -> bytes:
    """Encode ``frame`` as N1MM+'s ``<Spectrum>`` UTF-8 XML datagram.

    ``name`` is the source name N1MM+ shows and matches in its Spectrum
    Display settings. ``scaling`` converts each level to dB.
    """
    if not math.isfinite(scaling) or scaling <= 0:
        raise ValueError(f"scaling must be a positive finite number, got {scaling!r}")
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Spectrum>\n"
        f"\t<app>{_text(app, 'app')}</app>\n"
        f"\t<Name>{_text(name, 'name')}</Name>\n"
        f"\t<LowScopeFrequency>{format_khz(frame.low_hz)}</LowScopeFrequency>\n"
        f"\t<HighScopeFrequency>{format_khz(frame.high_hz)}</HighScopeFrequency>\n"
        f"\t<ScalingFactor>{scaling!r}</ScalingFactor>\n"
        f"\t<DataCount>{len(frame.levels)}</DataCount>\n"
        f"\t<SpectrumData>{','.join(map(str, frame.levels))}</SpectrumData>\n"
        "</Spectrum>"
    )
    payload = xml.encode("utf-8")
    if len(payload) > MAX_DATAGRAM:
        raise ValueError(
            f"encoded packet is {len(payload)} bytes, over the {MAX_DATAGRAM}-byte UDP limit"
        )
    return payload


class DatagramSocket(Protocol):
    def sendto(self, data: bytes, address: Any, /) -> int: ...

    def close(self) -> None: ...


Resolver = Callable[[str, int], tuple[int, Any]]
SocketFactory = Callable[[int], DatagramSocket]


def resolve_udp(host: str, port: int) -> tuple[int, Any]:
    """Resolve ``host:port`` once, returning ``(address family, sockaddr)``."""
    family, _, _, _, sockaddr = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)[0]
    return int(family), sockaddr


def _udp_socket(family: int) -> DatagramSocket:
    return socket.socket(family, socket.SOCK_DGRAM)


class N1mmSender:
    """Sends encoded packets to N1MM+ over UDP.

    Send failures (for example Windows reporting ``ConnectionResetError``
    after an ICMP port-unreachable while N1MM+ is closed) are counted and
    reported through the return value instead of raised, because the bridge
    must keep streaming until N1MM+ comes back.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        resolver: Resolver = resolve_udp,
        socket_factory: SocketFactory = _udp_socket,
    ) -> None:
        if not 0 < port < 65536:
            raise ValueError(f"port must be in 1..65535, got {port}")
        family, self._address = resolver(host, port)
        self._socket: DatagramSocket | None = socket_factory(family)
        self.sent = 0
        self.errors = 0
        self.last_error: OSError | None = None

    @property
    def address(self) -> Any:
        return self._address

    def send(self, payload: bytes) -> bool:
        """Send one datagram. Returns False (and counts the error) on failure."""
        if self._socket is None:
            raise RuntimeError("sender is closed")
        try:
            self._socket.sendto(payload, self._address)
        except OSError as err:
            self.errors += 1
            self.last_error = err
            return False
        self.sent += 1
        return True

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def __enter__(self) -> N1mmSender:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
