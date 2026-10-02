# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Fetch FTDI's real LibFT4222 and D2XX DLLs for CI's native tests (#37).

CI-ONLY: FTDI's libraries are proprietary. They are fetched on the runner,
checked against a pinned SHA-256 and (on Windows) their Authenticode
signatures, and never committed or bundled (the pre-commit hook and the
release regression's dist checks enforce that). See THIRD_PARTY.md.

The pin (URL, SHA-256, files, signers) lives in packaging/windows/ftdi_pin.json
and is shared with the installer and scripts/check_ftdi_download.py.

Source: ftdichip.com sits behind a Cloudflare browser challenge, so CI cannot
download from it. The PyPI ``ft4222`` wheel (MSR Electronics, MIT wrapper,
"LicenseRef-FTDI" for the DLLs) redistributes FTDI's unmodified Windows DLLs,
as FTDI's licence allows. Only the two DLLs are extracted:

- LibFT4222-64.dll 1.4.8.0 (the version wfview builds against), signed by
  Future Technology Devices International Ltd
- ftd2xx.dll 3.2.16.1 (FTDI CDM driver), WHQL-signed by Microsoft

    python scripts/fetch_ftdi.py --dest DIR          # verify, extract to DIR/lib
    python scripts/fetch_ftdi.py --dest DIR --print-hashes

In GitHub Actions the folder is exported as N1MM_BRIDGE_FTDI_DIR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Package:
    url: str
    sha256: str
    files: tuple[tuple[str, str], ...]
    """(path suffix inside the zip, name to extract as)."""

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]


PIN = Path(__file__).resolve().parent.parent / "packaging" / "windows" / "ftdi_pin.json"


def load_pin(path: Path = PIN) -> tuple[Package, dict[str, str]]:
    """The pinned download and expected signers, from the single source of truth (#133)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    files = tuple((f["member"], f["name"]) for f in data["files"])
    signers = {f["name"]: f["signer"] for f in data["files"]}
    return Package(data["url"], data["sha256"], files), signers


_PIN_PACKAGE, SIGNERS = load_pin()
PACKAGES = (_PIN_PACKAGE,)
"""Expected Authenticode signers (Windows only; checked after extraction)."""

Downloader = Callable[[str, Path], None]
SignatureCheck = Callable[[Path], str]
"""Returns the signer subject of a valid Authenticode signature, or raises FetchError."""


class FetchError(RuntimeError):
    pass


def curl_download(url: str, dest: Path) -> None:  # pragma: no cover - network
    result = subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "-o", str(dest), url],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FetchError(f"download failed ({result.returncode}): {url}\n{result.stderr}")


def authenticode_signer(path: Path) -> str:  # pragma: no cover - Windows CI only
    script = (
        f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; "
        "if ($s.Status -ne 'Valid') { Write-Output \"INVALID $($s.Status)\"; exit 1 }; "
        "Write-Output $s.SignerCertificate.Subject"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FetchError(f"{path.name}: Authenticode signature not valid: {result.stdout.strip()}")
    return result.stdout.strip()


def verify_signatures(files: Sequence[Path], check: SignatureCheck) -> None:
    for path in files:
        expected = SIGNERS.get(path.name)
        if expected is None:
            raise FetchError(f"no expected signer recorded for {path.name}")
        signer = check(path)
        if expected not in signer:
            raise FetchError(f"{path.name} is signed by {signer!r}, expected {expected!r}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract(archive: Path, files: Sequence[tuple[str, str]], out: Path) -> list[Path]:
    """Extract members whose path ends with each suffix (case-insensitive)."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        for suffix, target in files:
            match = [n for n in names if n.replace("\\", "/").lower().endswith(suffix.lower())]
            if len(match) != 1:
                raise FetchError(f"{archive.name}: expected one {suffix!r}, found {match}")
            path = out / target
            path.write_bytes(zf.read(match[0]))
            written.append(path)
    return written


def fetch(
    dest: Path,
    *,
    packages: Sequence[Package] = PACKAGES,
    download: Downloader = curl_download,
    print_hashes: bool = False,
    signature_check: SignatureCheck | None = (
        authenticode_signer if sys.platform == "win32" else None
    ),
    out: Callable[[str], object] = print,
) -> Path:
    """Download (if not cached), verify, and extract; return the DLL folder."""
    downloads, lib = dest / "downloads", dest / "lib"
    downloads.mkdir(parents=True, exist_ok=True)
    for pkg in packages:
        archive = downloads / pkg.filename
        if not archive.exists():
            download(pkg.url, archive)
        actual = sha256(archive)
        out(f"{pkg.filename} sha256={actual}")
        if print_hashes:
            with zipfile.ZipFile(archive) as zf:
                for name in zf.namelist():
                    if name.lower().endswith((".dll", "license.txt", "licence.txt")):
                        out(f"  {name}")
        if not print_hashes and actual != pkg.sha256:
            archive.unlink()
            raise FetchError(f"{pkg.filename}: SHA-256 {actual} does not match pinned {pkg.sha256}")
        if not print_hashes:
            written = extract(archive, pkg.files, lib)
            if signature_check is not None:
                verify_signatures(written, signature_check)
                out("Authenticode signatures valid: " + ", ".join(p.name for p in written))
    return lib


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - CI entry point
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--print-hashes", action="store_true")
    args = parser.parse_args(argv)
    try:
        lib = fetch(args.dest, print_hashes=args.print_hashes)
    except FetchError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    if not args.print_hashes:
        print(f"FTDI DLLs in {lib}: {sorted(p.name for p in lib.iterdir())}")
        env = os.environ.get("GITHUB_ENV")
        if env:
            with open(env, "a", encoding="utf-8") as fh:
                fh.write(f"N1MM_BRIDGE_FTDI_DIR={lib}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
