# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Check that the pinned FTDI LibFT4222 download still works (issue #133).

The Windows installer downloads FTDI's DLLs at install time from the URL in
packaging/windows/ftdi_pin.json. This check proves that URL still answers
HTTP 200 with exactly the pinned bytes, that both DLLs are inside, and (on
Windows) that their Authenticode signatures are valid and from the expected
signers. It runs in CI when the pin or installer changes, in the release
regression, and daily (.github/workflows/ftdi-download-check.yml).

    python scripts/check_ftdi_download.py            # exit 0 = OK
"""

from __future__ import annotations

import sys
import tempfile
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

import fetch_ftdi as ff

USER_AGENT = "n1mm-scope-bridge-ftdi-check (+https://github.com/Reid-n0rc/n1mm-scope-bridge)"

FIX_HINT = (
    "Fix: update packaging/windows/ftdi_pin.json (url, sha256) from PyPI's ft4222 "
    "release files and re-verify the DLL signatures (see AGENTS.md, Packaging)."
)

Fetch = Callable[[str, Path], int]
"""Download url to dest; return the HTTP status code (raise OSError on network failure)."""


def http_fetch(url: str, dest: Path) -> int:  # pragma: no cover - network
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as resp:
        dest.write_bytes(resp.read())
        return int(resp.status)


def _archive_problem(pkg: ff.Package, archive: Path, fetch: Fetch) -> str | None:
    try:
        status = fetch(pkg.url, archive)
    except OSError as err:
        return f"download failed: {err} ({pkg.url})"
    if status != 200:
        return f"download returned HTTP {status} ({pkg.url})"
    actual = ff.sha256(archive)
    if actual != pkg.sha256:
        return f"SHA-256 {actual} does not match the pinned {pkg.sha256}"
    return None


def _signature_problems(
    written: Sequence[Path], signers: dict[str, str], signature_check: ff.SignatureCheck
) -> list[str]:
    problems = []
    for path in written:
        try:
            signer = signature_check(path)
        except ff.FetchError as err:
            problems.append(str(err))
            continue
        if signers[path.name] not in signer:
            problems.append(f"{path.name} signed by {signer!r}, expected {signers[path.name]!r}")
    return problems


def check(
    *,
    pin: Path = ff.PIN,
    fetch: Fetch = http_fetch,
    signature_check: ff.SignatureCheck | None = (
        ff.authenticode_signer if sys.platform == "win32" else None
    ),
    workdir: Path | None = None,
    arch: str = ff.DEFAULT_ARCH,
) -> list[str]:
    """Return problems (empty when the download is healthy)."""
    pkg, signers = ff.load_pin(pin, arch)
    if not pkg.url.startswith("https://"):
        return [f"pinned URL is not HTTPS: {pkg.url}"]
    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        archive = Path(tmp) / pkg.filename
        problem = _archive_problem(pkg, archive, fetch)
        if problem:
            return [problem]
        try:
            written = ff.extract(archive, pkg.files, Path(tmp) / "lib")
        except (ff.FetchError, OSError, ValueError) as err:
            return [f"archive contents: {err}"]
        if signature_check is None:
            return []
        return _signature_problems(written, signers, signature_check)


def main(
    argv: Sequence[str] | None = None,
    *,
    out: Callable[[str], object] = print,
    pin: Path = ff.PIN,
    run_check: Callable[..., list[str]] | None = None,
) -> int:
    """Check every pinned architecture; exit 1 if any download is broken."""
    run = run_check or check
    failed = False
    signed = " and signatures" if sys.platform == "win32" else ""
    for arch in ff.pin_arches(pin):
        pkg, _ = ff.load_pin(pin, arch)
        problems = run(pin=pin, arch=arch)
        if problems:
            failed = True
            out(f"FTDI download check FAILED for {arch} ({pkg.filename}):")
            for problem in problems:
                out(f"  - {problem}")
        else:
            out(f"FTDI download OK for {arch}: {pkg.filename} (HTTP 200, SHA-256{signed} verified)")
    if failed:
        out(FIX_HINT)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
