# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Download FTDI's real LibFT4222 and D2XX DLLs for CI's native tests (#37).

CI-ONLY: FTDI's libraries are proprietary. They are downloaded from
ftdichip.com on the runner, checked against pinned SHA-256 hashes, and never
committed or bundled (the pre-commit hook and the release regression's dist
checks enforce that). See THIRD_PARTY.md.

    python scripts/fetch_ftdi.py --dest DIR          # verify, extract to DIR/lib
    python scripts/fetch_ftdi.py --dest DIR --print-hashes

Windows x64 only: LibFT4222-64.dll (LibFT4222 v1.4.8, the version wfview
builds against) and ftd2xx.dll (amd64/ftd2xx64.dll from FTDI's CDM driver
package; the driver installs it as System32\\ftd2xx.dll). In GitHub Actions the
extracted folder is exported as N1MM_BRIDGE_FTDI_DIR.
"""

from __future__ import annotations

import argparse
import hashlib
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


PACKAGES = (
    Package(
        "https://ftdichip.com/wp-content/uploads/2025/06/LibFT4222-v1.4.8.zip",
        "PIN-ME",
        (("imports/LibFT4222/dll/amd64/LibFT4222-64.dll", "LibFT4222-64.dll"),),
    ),
    Package(
        "https://ftdichip.com/wp-content/uploads/2025/03/CDM-v2.12.36.20-WHQL-Certified.zip",
        "PIN-ME",
        (("amd64/ftd2xx64.dll", "ftd2xx.dll"),),
    ),
)

Downloader = Callable[[str, Path], None]


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
            extract(archive, pkg.files, lib)
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
