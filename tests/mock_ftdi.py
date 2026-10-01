# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Build the mock FTDI library (tests/native/mock_ft4222.c) for native tests.

    uv run python tests/mock_ftdi.py OUT_DIR

Windows: ftd2xx.dll + LibFT4222-64.dll (or LibFT4222.dll on 32-bit Python),
with MSVC (``cl``) if available, else MinGW ``gcc``. Linux/macOS: one combined
libft4222.so / libft4222.dylib, like FTDI's own Linux library. Test-only:
the output is never committed or shipped (the pre-commit hook blocks it).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "native" / "mock_ft4222.c"

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class BuildUnavailable(RuntimeError):
    """No C compiler was found."""


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False)


def commands(
    out: Path,
    *,
    platform: str = sys.platform,
    is_64bit: bool = sys.maxsize > 2**32,
    which: Callable[[str], str | None] = shutil.which,
) -> list[list[str]]:
    """Compiler invocations that build the mock into ``out``."""
    src = str(SOURCE)
    if platform == "win32":
        ft_name = "LibFT4222-64.dll" if is_64bit else "LibFT4222.dll"
        parts = [("MOCK_D2XX", "ftd2xx.dll"), ("MOCK_FT4222", ft_name)]
        if which("cl"):
            return [
                ["cl", "/nologo", "/LD", "/MD", "/O2", f"/D{define}", src,
                 f"/Fe{out / name}", f"/Fo{out / (name + '.obj')}", "/link", "/NOLOGO"]
                for define, name in parts
            ]  # fmt: skip
        if which("gcc"):
            return [["gcc", "-shared", "-O2", f"-D{d}", "-o", str(out / n), src] for d, n in parts]
        raise BuildUnavailable("no C compiler (cl or gcc) on PATH")
    compiler = which("cc") or which("gcc") or which("clang")
    if not compiler:
        raise BuildUnavailable("no C compiler (cc, gcc, or clang) on PATH")
    name = "libft4222.dylib" if platform == "darwin" else "libft4222.so"
    return [[compiler, "-shared", "-fPIC", "-O2", "-DMOCK_D2XX", "-DMOCK_FT4222",
             "-o", str(out / name), src]]  # fmt: skip


def build(out: Path, *, runner: Runner = _run, **kw: object) -> Path:
    """Build the mock library into ``out`` and return that folder."""
    out.mkdir(parents=True, exist_ok=True)
    for cmd in commands(out, **kw):  # type: ignore[arg-type]
        result = runner(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"{cmd[0]} failed:\n{result.stdout}{result.stderr}")
    return out


if __name__ == "__main__":  # pragma: no cover
    print(build(Path(sys.argv[1])))
