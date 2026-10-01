# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import math
import socket
import xml.etree.ElementTree as ET
from typing import Any

import pytest

from n1mm_scope_bridge.n1mm import (
    DEFAULT_APP,
    DEFAULT_PORT,
    MAX_DATAGRAM,
    N1mmSender,
    encode_spectrum,
    format_khz,
    resolve_udp,
)
from n1mm_scope_bridge.spectrum import MAX_N1MM_LEVEL, SpectrumFrame

FRAME = SpectrumFrame(
    low_hz=14_024_000, high_hz=14_124_000, levels=(0, 1, 2, 254, 255), max_level=255
)

GOLDEN = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b"<Spectrum>\n"
    b"\t<app>n1mm-scope-bridge</app>\n"
    b"\t<Name>FT-710</Name>\n"
    b"\t<LowScopeFrequency>14024</LowScopeFrequency>\n"
    b"\t<HighScopeFrequency>14124</HighScopeFrequency>\n"
    b"\t<ScalingFactor>0.3125</ScalingFactor>\n"
    b"\t<DataCount>5</DataCount>\n"
    b"\t<SpectrumData>0,1,2,254,255</SpectrumData>\n"
    b"</Spectrum>"
)


# --- format_khz ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("hz", "expected"),
    [
        (0, "0"),
        (999, "0.999"),
        (1000, "1"),
        (14_074_000, "14074"),
        (14_074_500, "14074.5"),
        (14_074_550, "14074.55"),
        (7_000_001, "7000.001"),
        (1_296_000_000, "1296000"),
    ],
)
def test_format_khz(hz: int, expected: str) -> None:
    assert format_khz(hz) == expected


def test_format_khz_rejects_negative() -> None:
    with pytest.raises(ValueError, match=">= 0"):
        format_khz(-1)


# --- encode_spectrum -------------------------------------------------------------


def test_encode_matches_golden_packet() -> None:
    assert encode_spectrum(FRAME, name="FT-710", scaling=0.3125) == GOLDEN


def test_encoded_packet_is_well_formed_xml_in_manual_order() -> None:
    root = ET.fromstring(encode_spectrum(FRAME, name="FT-710", scaling=0.25))
    assert root.tag == "Spectrum"
    assert [child.tag for child in root] == [
        "app",
        "Name",
        "LowScopeFrequency",
        "HighScopeFrequency",
        "ScalingFactor",
        "DataCount",
        "SpectrumData",
    ]
    assert root.findtext("app") == DEFAULT_APP
    assert root.findtext("ScalingFactor") == "0.25"
    data = (root.findtext("SpectrumData") or "").split(",")
    assert int(root.findtext("DataCount") or "0") == len(data) == len(FRAME.levels)


def test_sub_khz_edges() -> None:
    f = SpectrumFrame(low_hz=14_073_500, high_hz=14_074_500, levels=(1,), max_level=255)
    root = ET.fromstring(encode_spectrum(f, name="x", scaling=1.0))
    assert root.findtext("LowScopeFrequency") == "14073.5"
    assert root.findtext("HighScopeFrequency") == "14074.5"


def test_name_and_app_are_escaped() -> None:
    payload = encode_spectrum(FRAME, name="A<&>\"'B", scaling=1.0, app="me & you")
    assert b"<Name>A&lt;&amp;&gt;&quot;&apos;B</Name>" in payload
    root = ET.fromstring(payload)
    assert root.findtext("Name") == "A<&>\"'B"
    assert root.findtext("app") == "me & you"


def test_non_ascii_name_is_utf8() -> None:
    payload = encode_spectrum(FRAME, name="Réid ⚡", scaling=1.0)
    assert "Réid ⚡".encode() in payload


@pytest.mark.parametrize("name", ["", "   ", "bad\nname", "tab\tname", "nul\x00"])
def test_invalid_names_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="name"):
        encode_spectrum(FRAME, name=name, scaling=1.0)


def test_invalid_app_rejected() -> None:
    with pytest.raises(ValueError, match="app"):
        encode_spectrum(FRAME, name="x", scaling=1.0, app="")


@pytest.mark.parametrize("scaling", [0.0, -0.5, math.inf, math.nan])
def test_invalid_scaling_rejected(scaling: float) -> None:
    with pytest.raises(ValueError, match="scaling"):
        encode_spectrum(FRAME, name="x", scaling=scaling)


def test_ft710_sized_frame_fits_comfortably() -> None:
    f = SpectrumFrame(low_hz=0, high_hz=1_000_000, levels=(255,) * 850, max_level=255)
    assert len(encode_spectrum(f, name="FT-710", scaling=0.3125)) < 4096


def test_oversized_packet_rejected() -> None:
    f = SpectrumFrame(
        low_hz=0, high_hz=1, levels=(MAX_N1MM_LEVEL,) * 12_000, max_level=MAX_N1MM_LEVEL
    )
    with pytest.raises(ValueError, match=str(MAX_DATAGRAM)):
        encode_spectrum(f, name="x", scaling=1.0)


# --- N1mmSender ------------------------------------------------------------------


class FakeSocket:
    def __init__(self, error: OSError | None = None) -> None:
        self.sent: list[tuple[bytes, Any]] = []
        self.error = error
        self.closed = 0

    def sendto(self, data: bytes, address: Any, /) -> int:
        if self.error is not None:
            raise self.error
        self.sent.append((data, address))
        return len(data)

    def close(self) -> None:
        self.closed += 1


def fake_sender(sock: FakeSocket, **kw: Any) -> tuple[N1mmSender, list[int]]:
    families: list[int] = []

    def factory(family: int) -> FakeSocket:
        families.append(family)
        return sock

    sender = N1mmSender(
        resolver=lambda host, port: (socket.AF_INET, (host, port)),
        socket_factory=factory,
        **kw,
    )
    return sender, families


def test_sender_defaults_to_localhost_13064() -> None:
    sock = FakeSocket()
    sender, families = fake_sender(sock)
    assert sender.address == ("127.0.0.1", DEFAULT_PORT)
    assert families == [socket.AF_INET]
    assert sender.send(b"hello") is True
    assert sock.sent == [(b"hello", ("127.0.0.1", 13064))]
    assert (sender.sent, sender.errors) == (1, 0)


def test_sender_counts_errors_without_raising() -> None:
    err = ConnectionResetError("port unreachable")
    sender, _ = fake_sender(FakeSocket(error=err))
    assert sender.send(b"x") is False
    assert sender.send(b"x") is False
    assert (sender.sent, sender.errors) == (0, 2)
    assert sender.last_error is err


def test_sender_close_is_idempotent_and_blocks_further_sends() -> None:
    sock = FakeSocket()
    sender, _ = fake_sender(sock)
    sender.close()
    sender.close()
    assert sock.closed == 1
    with pytest.raises(RuntimeError, match="closed"):
        sender.send(b"x")


def test_sender_context_manager_closes() -> None:
    sock = FakeSocket()
    sender, _ = fake_sender(sock)
    with sender as s:
        assert s is sender
    assert sock.closed == 1


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_sender_rejects_bad_port(port: int) -> None:
    with pytest.raises(ValueError, match="port"):
        fake_sender(FakeSocket(), port=port)


def test_resolve_udp_localhost() -> None:
    family, sockaddr = resolve_udp("127.0.0.1", 13064)
    assert family == socket.AF_INET
    assert sockaddr == ("127.0.0.1", 13064)


def test_loopback_round_trip() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(2)
        port = rx.getsockname()[1]
        payload = encode_spectrum(FRAME, name="FT-710", scaling=0.3125)
        with N1mmSender("127.0.0.1", port) as sender:
            assert sender.send(payload)
        data, _ = rx.recvfrom(MAX_DATAGRAM)
    assert data == payload
