# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import check_ftdi_download as cfd
import fetch_ftdi as ff
import pytest

MEMBERS = {"ft4222/LibFT4222-64.dll": b"lib", "ft4222/ftd2xx.dll": b"d2xx"}


def make_pin(
    tmp_path: Path, members: dict[str, bytes] = MEMBERS, *, url: str = "https://x.invalid/w.whl"
) -> tuple[Path, bytes]:
    wheel = tmp_path / "w.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    data = wheel.read_bytes()
    pin = tmp_path / "pin.json"
    pin.write_text(
        json.dumps(
            {
                "url": url,
                "sha256": hashlib.sha256(data).hexdigest(),
                "files": [
                    {
                        "member": "ft4222/LibFT4222-64.dll",
                        "name": "LibFT4222-64.dll",
                        "signer": "Future Technology Devices International",
                    },
                    {
                        "member": "ft4222/ftd2xx.dll",
                        "name": "ftd2xx.dll",
                        "signer": "Microsoft Windows Hardware Compatibility",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return pin, data


def serve(data: bytes, status: int = 200) -> cfd.Fetch:
    def fetch(url: str, dest: Path) -> int:
        dest.write_bytes(data)
        return status

    return fetch


def signers(mapping: dict[str, str]) -> ff.SignatureCheck:
    def check(path: Path) -> str:
        value = mapping[path.name]
        if value == "INVALID":
            raise ff.FetchError(f"{path.name}: Authenticode signature not valid: INVALID NotSigned")
        return value

    return check


GOOD_SIGNERS = {
    "LibFT4222-64.dll": "CN=Future Technology Devices International Ltd",
    "ftd2xx.dll": "CN=Microsoft Windows Hardware Compatibility Publisher",
}


def test_healthy_download(tmp_path: Path) -> None:
    pin, data = make_pin(tmp_path)
    assert cfd.check(pin=pin, fetch=serve(data), signature_check=signers(GOOD_SIGNERS)) == []
    assert cfd.check(pin=pin, fetch=serve(data), signature_check=None) == []


@pytest.mark.parametrize(
    ("fetch_kind", "message"),
    [
        ("404", "HTTP 404"),
        ("oserror", "download failed"),
        ("bad-bytes", "does not match the pinned"),
    ],
)
def test_broken_downloads(tmp_path: Path, fetch_kind: str, message: str) -> None:
    pin, data = make_pin(tmp_path)

    def failing(url: str, dest: Path) -> int:
        raise OSError("connection refused")

    fetch = {"404": serve(data, 404), "oserror": failing, "bad-bytes": serve(data + b"x")}[
        fetch_kind
    ]
    problems = cfd.check(pin=pin, fetch=fetch, signature_check=None)
    assert len(problems) == 1
    assert message in problems[0]


def test_missing_dll_in_archive(tmp_path: Path) -> None:
    pin, data = make_pin(tmp_path, {"ft4222/LibFT4222-64.dll": b"lib"})
    problems = cfd.check(pin=pin, fetch=serve(data), signature_check=None)
    assert problems
    assert "archive contents" in problems[0]


def test_bad_signatures(tmp_path: Path) -> None:
    pin, data = make_pin(tmp_path)
    wrong = {"LibFT4222-64.dll": "CN=Someone Else", "ftd2xx.dll": "INVALID"}
    problems = cfd.check(pin=pin, fetch=serve(data), signature_check=signers(wrong))
    assert any("expected 'Future Technology" in p for p in problems)
    assert any("not valid" in p for p in problems)


def test_non_https_pin_rejected(tmp_path: Path) -> None:
    pin, data = make_pin(tmp_path, url="http://x.invalid/w.whl")
    assert "not HTTPS" in cfd.check(pin=pin, fetch=serve(data), signature_check=None)[0]


def test_main_reports_every_arch() -> None:
    lines: list[str] = []
    seen: list[str] = []

    def ok(*, pin: Path, arch: str) -> list[str]:
        seen.append(arch)
        return []

    assert cfd.main([], out=lines.append, run_check=ok) == 0
    assert seen == list(ff.pin_arches())
    assert all(line.startswith("FTDI download OK for ") for line in lines)
    assert any(" i386: " in line for line in lines)


def test_main_fails_if_any_arch_is_broken() -> None:
    lines: list[str] = []

    def broken_i386(*, pin: Path, arch: str) -> list[str]:
        return ["download returned HTTP 404 (u)"] if arch == "i386" else []

    assert cfd.main([], out=lines.append, run_check=broken_i386) == 1
    assert any(line.startswith("FTDI download OK for amd64") for line in lines)
    assert any("FAILED for i386" in line for line in lines)
    assert any("ftdi_pin.json" in line for line in lines)


def test_check_uses_the_requested_arch(tmp_path: Path) -> None:
    pin, data = make_pin(tmp_path)
    raw = json.loads(pin.read_text(encoding="utf-8"))
    raw["arches"] = {
        "i386": {"url": "https://x.invalid/other.whl", "sha256": "0" * 64, "files": raw["files"]}
    }
    pin.write_text(json.dumps(raw), encoding="utf-8")
    problems = cfd.check(pin=pin, fetch=serve(data), signature_check=None, arch="i386")
    assert problems
    assert "SHA-256" in problems[0] or "sha" in problems[0].lower()
