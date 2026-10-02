# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import fetch_ftdi as ff
import pytest


def make_zip(path: Path, members: dict[str, bytes]) -> bytes:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path.read_bytes()


def package(
    tmp_path: Path, members: dict[str, bytes], files: tuple[tuple[str, str], ...]
) -> ff.Package:
    data = make_zip(tmp_path / "src.zip", members)
    return ff.Package("https://example.invalid/pkg.zip", hashlib.sha256(data).hexdigest(), files)


def downloader(tmp_path: Path, calls: list[str]) -> ff.Downloader:
    def download(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes((tmp_path / "src.zip").read_bytes())

    return download


def test_fetch_verifies_extracts_and_caches(tmp_path: Path) -> None:
    pkg = package(
        tmp_path,
        {
            "LibFT4222-v1.4.8/imports/LibFT4222/dll/amd64/LibFT4222-64.dll": b"dll",
            "readme.txt": b"x",
        },
        (("imports/LibFT4222/dll/amd64/LibFT4222-64.dll", "LibFT4222-64.dll"),),
    )
    calls: list[str] = []
    lib = ff.fetch(
        tmp_path / "out", packages=[pkg], download=downloader(tmp_path, calls), out=lambda _: None
    )
    assert (lib / "LibFT4222-64.dll").read_bytes() == b"dll"
    ff.fetch(
        tmp_path / "out", packages=[pkg], download=downloader(tmp_path, calls), out=lambda _: None
    )
    assert len(calls) == 1  # second run uses the cached download


def test_fetch_renames_and_matches_case_insensitively(tmp_path: Path) -> None:
    pkg = package(
        tmp_path, {"CDM\\AMD64\\FTD2XX64.DLL": b"d2xx"}, (("amd64/ftd2xx64.dll", "ftd2xx.dll"),)
    )
    lib = ff.fetch(
        tmp_path / "out", packages=[pkg], download=downloader(tmp_path, []), out=lambda _: None
    )
    assert (lib / "ftd2xx.dll").read_bytes() == b"d2xx"


def test_hash_mismatch_fails_and_discards_download(tmp_path: Path) -> None:
    good = package(tmp_path, {"a/x.dll": b"1"}, (("x.dll", "x.dll"),))
    bad = ff.Package(good.url, "0" * 64, good.files)
    with pytest.raises(ff.FetchError, match="does not match pinned"):
        ff.fetch(
            tmp_path / "out", packages=[bad], download=downloader(tmp_path, []), out=lambda _: None
        )
    assert not (tmp_path / "out" / "downloads" / "pkg.zip").exists()


def test_print_hashes_lists_dlls_without_verifying(tmp_path: Path) -> None:
    good = package(tmp_path, {"a/x.dll": b"1", "a/LICENSE.txt": b"l"}, (("x.dll", "x.dll"),))
    unpinned = ff.Package(good.url, "PIN-ME", good.files)
    lines: list[str] = []
    ff.fetch(
        tmp_path / "out",
        packages=[unpinned],
        download=downloader(tmp_path, []),
        print_hashes=True,
        out=lines.append,
    )
    assert lines[0] == f"pkg.zip sha256={good.sha256}"
    assert "  a/x.dll" in lines
    assert "  a/LICENSE.txt" in lines


@pytest.mark.parametrize("members", [{}, {"a/x.dll": b"1", "b/x.dll": b"2"}])
def test_extract_requires_exactly_one_match(tmp_path: Path, members: dict[str, bytes]) -> None:
    make_zip(tmp_path / "p.zip", members)
    with pytest.raises(ff.FetchError, match="expected one"):
        ff.extract(tmp_path / "p.zip", [("x.dll", "x.dll")], tmp_path / "lib")


def test_pinned_packages_are_ftdi_https_and_x64() -> None:
    names = [p.filename for p in ff.PACKAGES]
    assert names == ["LibFT4222-v1.4.8.zip", "CDM-v2.12.36.20-WHQL-Certified.zip"]
    assert all(p.url.startswith("https://ftdichip.com/") for p in ff.PACKAGES)
    targets = {target for p in ff.PACKAGES for _, target in p.files}
    assert targets == {"LibFT4222-64.dll", "ftd2xx.dll"}
