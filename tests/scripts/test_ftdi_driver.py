# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import ftdi_driver as fd
import pytest

PAYLOAD = b"MSCF fake driver cab"


def pin_for(payload: bytes, **over: object) -> fd.DriverPin:
    sha1 = hashlib.sha1(payload).hexdigest()
    base: dict[str, object] = {
        "version": "2.12.36.20",
        "url": f"https://catalog.s.download.windowsupdate.com/x/y_{sha1}.cab",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "sha1": sha1,
        "size": len(payload),
        "filename": "ftdi.cab",
        "inf": "ftdibus.inf",
        "catalog": "ftdibus.cat",
        "hardware_id": "USB\\VID_0403&PID_601C",
        "signer": "Microsoft Windows Hardware Compatibility Publisher",
        "ftdichip_probe_url": "https://ftdichip.com/drivers/d2xx-drivers/",
    }
    base.update(over)
    return fd.DriverPin(**base)  # type: ignore[arg-type]


def serving(payload: bytes, status: int = 200) -> fd.Fetch:
    def fetch(url: str, dest: Path) -> int:
        dest.write_bytes(payload)
        return status

    return fetch


def test_committed_pin_is_valid() -> None:
    pin = fd.load_pin()
    assert pin.url.startswith("https://catalog.s.download.windowsupdate.com/")
    assert pin.sha1 in pin.url
    assert pin.hardware_id == "USB\\VID_0403&PID_601C"
    assert pin.inf == "ftdibus.inf"


def test_load_pin_rejects_mismatched_sha1(tmp_path: Path) -> None:
    data = json.loads(fd.PIN.read_text(encoding="utf-8"))
    data["sha1"] = "0" * 40
    path = tmp_path / "pin.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-1"):
        fd.load_pin(path)


def test_load_pin_rejects_http(tmp_path: Path) -> None:
    data = json.loads(fd.PIN.read_text(encoding="utf-8"))
    data["url"] = data["url"].replace("https://", "http://")
    path = tmp_path / "pin.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="https"):
        fd.load_pin(path)


def test_installer_defines_follow_the_pin() -> None:
    defines = dict(d[2:].split("=", 1) for d in fd.installer_defines())
    pin = fd.load_pin()
    assert defines["FtdiDriverUrl"] == pin.url
    assert defines["FtdiDriverSha256"] == pin.sha256
    assert defines["FtdiDriverInf"] == "ftdibus.inf"
    assert defines["FtdiDriverSigner"].startswith("Microsoft")


def test_check_package_ok_off_windows(tmp_path: Path) -> None:
    assert fd.check_package(pin_for(PAYLOAD), tmp_path, fetch=serving(PAYLOAD), windows=False) == []


@pytest.mark.parametrize(
    ("fetch", "message"),
    [
        (serving(PAYLOAD, 404), "HTTP 404"),
        (serving(b"different bytes!!!!!"), "SHA256"),
        (serving(PAYLOAD + b"x"), "size"),
    ],
)
def test_check_package_problems(tmp_path: Path, fetch: fd.Fetch, message: str) -> None:
    problems = fd.check_package(pin_for(PAYLOAD), tmp_path, fetch=fetch, windows=False)
    assert any(message in p for p in problems)


def test_check_package_network_error(tmp_path: Path) -> None:
    def boom(url: str, dest: Path) -> int:
        raise OSError("connection reset")

    assert "connection reset" in fd.check_package(pin_for(PAYLOAD), tmp_path, fetch=boom)[0]


def runner_writing(message: str, code: int = 0) -> fd.Runner:
    def run(cmd: Sequence[str]) -> tuple[int, str]:
        result = Path(cmd[cmd.index("-Result") + 1])
        result.write_text(message, encoding="ascii")
        assert cmd[cmd.index("-Mode") + 1] == "Verify"
        assert cmd[cmd.index("-HardwareId") + 1] == "USB\\VID_0403&PID_601C"
        return code, ""

    return run


def test_check_package_runs_signature_verify_on_windows(tmp_path: Path) -> None:
    pin = pin_for(PAYLOAD)
    ok = fd.check_package(
        pin, tmp_path, fetch=serving(PAYLOAD), runner=runner_writing("OK"), windows=True
    )
    assert ok == []
    failing = runner_writing("ERROR: ftdibus.cat signature is not valid (HashMismatch)", 1)
    bad = fd.check_package(pin, tmp_path, fetch=serving(PAYLOAD), runner=failing, windows=True)
    assert "signature is not valid" in bad[0]


def test_ftdichip_status_detects_cloudflare(tmp_path: Path) -> None:
    challenge = b"<!DOCTYPE html><html><head><title>Just a moment...</title>"
    assert "Cloudflare" in fd.ftdichip_status(
        pin_for(PAYLOAD), tmp_path, fetch=serving(challenge, 403)
    )
    assert "reachable by scripts" in fd.ftdichip_status(
        pin_for(PAYLOAD), tmp_path, fetch=serving(b"<html>drivers</html>")
    )
    assert fd.ftdichip_status(pin_for(PAYLOAD), tmp_path, fetch=serving(b"x", 500)) == "HTTP 500"


def test_ftdichip_status_unreachable(tmp_path: Path) -> None:
    def boom(url: str, dest: Path) -> int:
        raise OSError("timed out")

    assert fd.ftdichip_status(pin_for(PAYLOAD), tmp_path, fetch=boom).startswith("unreachable")


def test_main_reports(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    pin = fd.load_pin()
    payload = b"z" * pin.size
    monkeypatch.setattr(fd, "load_pin", lambda: pin_for(payload))
    assert fd.main(["check"], fetch=serving(payload), windows=False) == 0
    assert "OK: FTDI driver" in capsys.readouterr().out
    assert fd.main(["check"], fetch=serving(b"nope"), windows=False) == 1
    assert "Fix:" in capsys.readouterr().out
    assert fd.main(["ftdichip"], fetch=serving(b"<html/>")) == 0
    assert fd.main(["bogus"], fetch=serving(b"")) == 2
