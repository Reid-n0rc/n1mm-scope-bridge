# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""FTDI USB driver package: pin, installer defines, and download check (issue #152).

The Windows installer can install FTDI's WHQL D2XX driver (needed for the radio's
FT4222H scope interface, USB VID_0403 PID_601C) when Windows doesn't have it yet.
FTDI's own site blocks scripted downloads with a Cloudflare challenge, so the
package comes from Microsoft Update Catalog, pinned in
packaging/windows/ftdi_driver_pin.json.

    python scripts/ftdi_driver.py check      # download + verify the pinned package
    python scripts/ftdi_driver.py ftdichip   # report whether ftdichip.com is scriptable

`check` proves HTTP 200, exact size, SHA-256 and SHA-1; on Windows it also runs
packaging/windows/ftdi_driver.ps1 -Mode Verify (catalog signature, INF lists the
FT4222H). Exit code 0 = OK.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "packaging" / "windows" / "ftdi_driver_pin.json"
HELPER = ROOT / "packaging" / "windows" / "ftdi_driver.ps1"
USER_AGENT = "n1mm-scope-bridge-ftdi-check (+https://github.com/Reid-n0rc/n1mm-scope-bridge)"
CHALLENGE_MARKERS = ("Just a moment...", "cf-chl", "challenge-platform")

Fetch = Callable[[str, Path], int]
"""Download url to dest and return the HTTP status (raise OSError on network failure)."""
Runner = Callable[[Sequence[str]], tuple[int, str]]


@dataclass(frozen=True)
class DriverPin:
    version: str
    url: str
    sha256: str
    sha1: str
    size: int
    filename: str
    inf: str
    catalog: str
    hardware_id: str
    signer: str
    ftdichip_probe_url: str


def load_pin(path: Path = PIN) -> DriverPin:
    data = json.loads(path.read_text(encoding="utf-8"))
    pin = DriverPin(
        version=data["version"],
        url=data["url"],
        sha256=data["sha256"].lower(),
        sha1=data["sha1"].lower(),
        size=int(data["size"]),
        filename=data["filename"],
        inf=data["inf"],
        catalog=data["catalog"],
        hardware_id=data["hardware_id"],
        signer=data["signer"],
        ftdichip_probe_url=data["ftdichip_probe_url"],
    )
    if not pin.url.startswith("https://") or len(pin.sha256) != 64 or len(pin.sha1) != 40:
        raise ValueError(f"{path.name}: url must be https and hashes must be SHA-256/SHA-1 hex")
    if pin.sha1 not in pin.url:
        raise ValueError(f"{path.name}: Microsoft catalog URLs embed the SHA-1; it doesn't match")
    return pin


def installer_defines(pin: DriverPin | None = None) -> list[str]:
    """Inno Setup /D defines for the optional "Install FTDI USB driver" task."""
    pin = pin or load_pin()
    return [
        f"/DFtdiDriverUrl={pin.url}",
        f"/DFtdiDriverSha256={pin.sha256}",
        f"/DFtdiDriverFile={pin.filename}",
        f"/DFtdiDriverVersion={pin.version}",
        f"/DFtdiDriverSigner={pin.signer}",
        f"/DFtdiDriverInf={pin.inf}",
        f"/DFtdiDriverCatalog={pin.catalog}",
    ]


def http_fetch(url: str, dest: Path) -> int:  # pragma: no cover - network
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            dest.write_bytes(resp.read())
            return int(resp.status)
    except urllib.error.HTTPError as err:
        dest.write_bytes(err.read())
        return int(err.code)


def run_command(cmd: Sequence[str]) -> tuple[int, str]:  # pragma: no cover - Windows only
    proc = subprocess.run(list(cmd), capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr


def _digest(path: Path, name: str) -> str:
    h = hashlib.new(name)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_package(
    pin: DriverPin,
    workdir: Path,
    *,
    fetch: Fetch = http_fetch,
    runner: Runner = run_command,
    windows: bool = sys.platform == "win32",
) -> list[str]:
    """Problems with the pinned driver package (empty list = OK)."""
    cab = workdir / pin.filename
    try:
        status = fetch(pin.url, cab)
    except OSError as err:
        return [f"download failed: {err} ({pin.url})"]
    if status != 200:
        return [f"download returned HTTP {status} ({pin.url})"]
    problems = []
    size = cab.stat().st_size
    if size != pin.size:
        problems.append(f"size {size} bytes does not match the pinned {pin.size}")
    for name, expected in (("sha256", pin.sha256), ("sha1", pin.sha1)):
        actual = _digest(cab, name)
        if actual != expected:
            problems.append(f"{name.upper()} {actual} does not match the pinned {expected}")
    if problems or not windows:
        return problems
    result = workdir / "verify.txt"
    code, out = runner(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HELPER),
         "-Mode", "Verify", "-Cab", str(cab), "-Result", str(result), "-Signer", pin.signer,
         "-Inf", pin.inf, "-Catalog", pin.catalog, "-HardwareId", pin.hardware_id]
    )  # fmt: skip
    message = result.read_text(encoding="ascii").strip() if result.exists() else out.strip()
    if code != 0 or message != "OK":
        problems.append(f"package verification failed: {message or f'exit code {code}'}")
    return problems


def ftdichip_status(pin: DriverPin, workdir: Path, *, fetch: Fetch = http_fetch) -> str:
    """Whether ftdichip.com can be downloaded from by a script (it usually can't)."""
    page = workdir / "ftdichip.html"
    try:
        status = fetch(pin.ftdichip_probe_url, page)
    except OSError as err:
        return f"unreachable ({err})"
    text = page.read_bytes()[:20000].decode("utf-8", errors="replace") if page.exists() else ""
    if any(marker in text for marker in CHALLENGE_MARKERS):
        return f"blocked by a Cloudflare browser challenge (HTTP {status})"
    if status != 200:
        return f"HTTP {status}"
    return "reachable by scripts (consider using FTDI's own downloads again, #152)"


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch: Fetch = http_fetch,
    runner: Runner = run_command,
    windows: bool = sys.platform == "win32",
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "check"
    pin = load_pin()
    with tempfile.TemporaryDirectory() as tmp:
        if command == "ftdichip":
            print(f"ftdichip.com: {ftdichip_status(pin, Path(tmp), fetch=fetch)}")
            return 0
        if command != "check":
            print(f"unknown command {command!r}; use check or ftdichip", file=sys.stderr)
            return 2
        problems = check_package(pin, Path(tmp), fetch=fetch, runner=runner, windows=windows)
        print(f"ftdichip.com: {ftdichip_status(pin, Path(tmp), fetch=fetch)}")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        print(
            "Fix: find the current 'FTDI - USB' driver for VID_0403&PID_601C on Microsoft Update "
            "Catalog, update packaging/windows/ftdi_driver_pin.json (url, sha256, sha1, size, "
            "version) and re-run this check on Windows."
        )
        return 1
    print(f"OK: FTDI driver {pin.version} package is downloadable and verified ({pin.url})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
