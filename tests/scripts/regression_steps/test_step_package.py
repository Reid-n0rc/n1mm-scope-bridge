# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import io
import tarfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

import pytest
from regression_core import CheckFailed
from stepload import fake_runner, load_step

pkg = load_step("50_package")


LIC = ".dist-info/licenses/"


def make_wheel(path: Path, extra: Sequence[str] = (), drop: str = "") -> Path:
    names = ["n1mm_scope_bridge/__init__.py"] + [f"pkg-0.1{LIC}{n}" for n in pkg.LICENSE_FILES]
    with zipfile.ZipFile(path, "w") as zf:
        for name in [n for n in names if not (drop and n.endswith(drop))] + list(extra):
            zf.writestr(name, "x")
    return path


def make_sdist(path: Path, extra: Sequence[str] = (), drop: str = "") -> Path:
    names = [
        *pkg.LICENSE_FILES,
        "pyproject.toml",
        "src/n1mm_scope_bridge/__init__.py",
        "tests/t.py",
    ]
    with tarfile.open(path, "w:gz") as tf:
        for name in [n for n in names if n != drop] + list(extra):
            info = tarfile.TarInfo(f"pkg-0.1/{name}")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
    return path


def test_good_archives_pass(tmp_path: Path) -> None:
    make_wheel(tmp_path / "p.whl")
    make_sdist(tmp_path / "p.tar.gz")
    pkg.check_dists(tmp_path)


@pytest.mark.parametrize("lic", pkg.LICENSE_FILES)
def test_wheel_missing_license(tmp_path: Path, lic: str) -> None:
    with pytest.raises(CheckFailed, match=f"licenses/{lic}"):
        pkg.check_wheel(make_wheel(tmp_path / "p.whl", drop=lic))


def test_wheel_without_package(tmp_path: Path) -> None:
    with pytest.raises(CheckFailed, match="does not contain the package"):
        pkg.check_wheel(make_wheel(tmp_path / "p.whl", drop="__init__.py"))


@pytest.mark.parametrize("binary", ["lib/LibFT4222-64.dll", "x/ftd2xx.dll", "libft4222.so.1.4"])
def test_archives_reject_ftdi_binaries(tmp_path: Path, binary: str) -> None:
    with pytest.raises(CheckFailed, match="FTDI"):
        pkg.check_wheel(make_wheel(tmp_path / "p.whl", extra=[binary]))
    with pytest.raises(CheckFailed, match="FTDI"):
        pkg.check_sdist(make_sdist(tmp_path / "p.tar.gz", extra=[binary]))


@pytest.mark.parametrize(
    ("drop", "message"),
    [
        ("NOTICE", "missing NOTICE"),
        ("pyproject.toml", "missing pyproject"),
        ("tests/t.py", "no tests/"),
    ],
)
def test_sdist_requirements(tmp_path: Path, drop: str, message: str) -> None:
    with pytest.raises(CheckFailed, match=message):
        pkg.check_sdist(make_sdist(tmp_path / "p.tar.gz", drop=drop))


def test_check_dists_needs_exactly_one_of_each(tmp_path: Path) -> None:
    with pytest.raises(CheckFailed, match="expected one wheel"):
        pkg.check_dists(tmp_path)


def test_wheel_smoke_runs_install_and_notices(tmp_path: Path) -> None:
    make_wheel(tmp_path / "p.whl")
    runner = fake_runner(output="ABSOLUTELY NO WARRANTY")
    pkg.wheel_smoke(tmp_path, runner)
    calls = runner.calls  # type: ignore[attr-defined]
    assert [c[0] for c in calls[:2]] == ["uv", "uv"]
    assert calls[2][-1] == "--version"
    assert calls[3][-1] == "--license"


def test_wheel_smoke_failures(tmp_path: Path) -> None:
    with pytest.raises(CheckFailed, match="no wheel"):
        pkg.wheel_smoke(tmp_path, fake_runner())
    make_wheel(tmp_path / "p.whl")
    with pytest.raises(CheckFailed, match="failed"):
        pkg.wheel_smoke(tmp_path, fake_runner({"uv": 1}))
    with pytest.raises(CheckFailed, match="legal notice"):
        pkg.wheel_smoke(tmp_path, fake_runner(output="n1mm-scope-bridge 0.1.0"))


def test_build_step_reports_failure(tmp_path: Path) -> None:
    with pytest.raises(CheckFailed, match="uv build failed"):
        pkg.build(fake_runner({"uv": 2}), dist=tmp_path / "dist")
    pkg.build(fake_runner(), dist=tmp_path / "dist")


def test_package_steps() -> None:
    names = [s.name for s in pkg.steps(load_step("10_environment").StepContext(fake_runner()))]
    assert names == [
        "Build sdist and wheel",
        "Dist contents (licenses, source, no FTDI binaries)",
        "Wheel installs and shows legal notices",
    ]
