# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Build the sdist and wheel, check their contents, and install the wheel."""

from __future__ import annotations

import fnmatch
import shutil
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

from regression_core import DIST, CheckFailed, Runner, Step, StepContext, run_command, tail

LICENSE_FILES = ("LICENSE", "NOTICE", "THIRD_PARTY.md")
FORBIDDEN = ("*ft4222*.dll", "*ft4222*.so*", "*ft4222*.dylib", "*ftd2xx*")


def _forbidden(names: Sequence[str]) -> list[str]:
    return [n for n in names for pat in FORBIDDEN if fnmatch.fnmatch(n.lower(), pat)]


def check_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    for lic in LICENSE_FILES:
        if not any(n.endswith(f".dist-info/licenses/{lic}") for n in names):
            raise CheckFailed(f"{path.name} is missing licenses/{lic}")
    if not any(n.endswith("n1mm_scope_bridge/__init__.py") for n in names):
        raise CheckFailed(f"{path.name} does not contain the package")
    if bad := _forbidden(names):
        raise CheckFailed(f"{path.name} contains FTDI binaries: {bad}")


def check_sdist(path: Path) -> None:
    with tarfile.open(path) as tf:
        names = [n.split("/", 1)[1] for n in tf.getnames() if "/" in n]
    for required in (*LICENSE_FILES, "pyproject.toml"):
        if required not in names:
            raise CheckFailed(f"{path.name} is missing {required}")
    for prefix in ("src/n1mm_scope_bridge/", "tests/"):
        if not any(n.startswith(prefix) for n in names):
            raise CheckFailed(f"{path.name} has no {prefix} (GPLv3 corresponding source)")
    if bad := _forbidden(names):
        raise CheckFailed(f"{path.name} contains FTDI binaries: {bad}")


def check_dists(dist: Path = DIST) -> None:
    wheels, sdists = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise CheckFailed(f"expected one wheel and one sdist in {dist}, found {wheels + sdists}")
    check_wheel(wheels[0])
    check_sdist(sdists[0])


def wheel_smoke(dist: Path = DIST, runner: Runner = run_command) -> None:
    """Install the wheel into a fresh venv and run the CLI's legal notices."""
    wheel = next(iter(sorted(dist.glob("*.whl"))), None)
    if wheel is None:
        raise CheckFailed(f"no wheel in {dist}")
    with tempfile.TemporaryDirectory() as tmp:
        venv = Path(tmp) / "venv"
        exe = venv / ("Scripts" if sys.platform == "win32" else "bin") / "n1mm-scope-bridge"
        for cmd in (
            ("uv", "venv", "--quiet", str(venv)),
            ("uv", "pip", "install", "--quiet", "--python", str(venv), str(wheel)),
            (str(exe), "--version"),
            (str(exe), "--license"),
        ):
            code, out = runner(cmd)
            if code != 0:
                raise CheckFailed(f"{' '.join(cmd)} failed ({code}):\n{tail(out)}")
            if cmd[-1] == "--version" and "ABSOLUTELY NO WARRANTY" not in out:
                raise CheckFailed("--version does not show the GPL legal notice")


def build(runner: Runner, dist: Path = DIST) -> None:
    shutil.rmtree(dist, ignore_errors=True)
    code, out = runner(("uv", "build", "--out-dir", str(dist)))
    if code != 0:
        raise CheckFailed(f"uv build failed ({code}):\n{tail(out)}")


def steps(ctx: StepContext) -> list[Step]:
    return [
        Step("Build sdist and wheel", action=lambda: build(ctx.runner)),
        Step("Dist contents (licenses, source, no FTDI binaries)", action=check_dists),
        Step(
            "Wheel installs and shows legal notices", action=lambda: wheel_smoke(runner=ctx.runner)
        ),
    ]
