# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Full release regression for release candidates and releases (issue #16).

Runs every check a release must pass, in order, stops at the first failure,
and writes a Markdown report. Standard library only, so it can run with any
Python before the project environment exists:

    uv run --no-project python scripts/release_regression.py --report regression-report.md

Windows-only steps (app, installer, GUI) are skipped with --skip-windows-only
and marked SKIPPED in the report. A release requires a Windows run with no
skips. Every new user-facing feature adds its step here (AGENTS.md).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "regression"
LICENSE_FILES = ("LICENSE", "NOTICE", "THIRD_PARTY.md")
FIXTURE = ROOT / "tests" / "fixtures" / "ft710_synthetic.cap"
MIN_PACKETS = 5
DRAIN_TIMEOUT = 0.5
FORBIDDEN = ("*ft4222*.dll", "*ft4222*.so*", "*ft4222*.dylib", "*ftd2xx*")
OUTPUT_TAIL = 40


class CheckFailed(Exception):
    """A callable step found a problem."""


Action = Callable[[], None]


@dataclass(frozen=True)
class Step:
    name: str
    command: tuple[str, ...] = ()
    action: Action | None = None
    windows_only: bool = False
    disabled_reason: str = ""


@dataclass(frozen=True)
class Result:
    name: str
    status: str  # PASS, FAIL, SKIPPED, NOT RUN
    seconds: float = 0.0
    detail: str = ""
    command: str = ""


Runner = Callable[[Sequence[str]], tuple[int, str]]


def run_command(command: Sequence[str]) -> tuple[int, str]:  # pragma: no cover - real processes
    proc = subprocess.run(
        list(command), cwd=ROOT, capture_output=True, text=True, check=False, errors="replace"
    )
    return proc.returncode, proc.stdout + proc.stderr


def _tail(text: str, lines: int = OUTPUT_TAIL) -> str:
    return "\n".join(text.rstrip().splitlines()[-lines:])


def run_steps(
    steps: Sequence[Step],
    *,
    runner: Runner = run_command,
    skip_windows_only: bool = False,
    is_windows: bool = sys.platform == "win32",
    clock: Callable[[], float] = time.monotonic,
) -> list[Result]:
    """Run steps in order; after the first failure the rest are NOT RUN."""
    results: list[Result] = []
    failed = False
    for step in steps:
        shown = " ".join(step.command)
        if failed:
            results.append(Result(step.name, "NOT RUN", command=shown))
            continue
        if step.disabled_reason:
            results.append(Result(step.name, "SKIPPED", detail=step.disabled_reason, command=shown))
            continue
        if step.windows_only and (skip_windows_only or not is_windows):
            why = "--skip-windows-only" if skip_windows_only else "not running on Windows"
            results.append(Result(step.name, "SKIPPED", detail=why, command=shown))
            continue
        start = clock()
        if step.action is not None:
            try:
                step.action()
                status, detail = "PASS", ""
            except CheckFailed as err:
                status, detail = "FAIL", str(err)
        else:
            code, output = runner(step.command)
            status = "PASS" if code == 0 else "FAIL"
            detail = "" if code == 0 else f"exit code {code}\n{_tail(output)}"
        results.append(Result(step.name, status, clock() - start, detail, shown))
        failed = status == "FAIL"
    return results


def passed(results: Sequence[Result], *, allow_skips: bool) -> bool:
    if any(r.status in ("FAIL", "NOT RUN") for r in results):
        return False
    return allow_skips or not any(r.status == "SKIPPED" for r in results)


def render_report(results: Sequence[Result], meta: dict[str, str], *, ok: bool) -> str:
    lines = [
        "# Release regression report",
        "",
        f"**Result: {'PASS' if ok else 'FAIL'}**",
        "",
        *[f"- {key}: `{value}`" for key, value in meta.items()],
        "",
        "| # | Step | Result | Time (s) |",
        "|---|------|--------|---------:|",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"| {i} | {r.name} | {r.status} | {r.seconds:.1f} |")
    details = [r for r in results if r.detail]
    if details:
        lines += ["", "## Details"]
        for r in details:
            lines += ["", f"### {r.name} ({r.status})"]
            if r.command:
                lines += ["", f"`{r.command}`"]
            lines += ["", "```", r.detail, "```"]
    return "\n".join(lines) + "\n"


# --- archive checks ---------------------------------------------------------------


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
                raise CheckFailed(f"{' '.join(cmd)} failed ({code}):\n{_tail(out)}")
            if cmd[-1] == "--version" and "ABSOLUTELY NO WARRANTY" not in out:
                raise CheckFailed("--version does not show the GPL legal notice")


def e2e_replay(runner: Runner = run_command, fixture: Path = FIXTURE) -> None:
    """Replay the synthetic capture through the real CLI into a UDP listener."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 21)
        rx.bind(("127.0.0.1", 0))
        port = str(rx.getsockname()[1])
        cmd = ("uv", "run", "n1mm-scope-bridge", "run", "--replay", str(fixture), "--loop",
               "--duration", "2", "--rate", "10", "--port", port)  # fmt: skip
        code, out = runner(cmd)
        if code != 0:
            raise CheckFailed(f"bridge exited {code}:\n{_tail(out)}")
        # Drain until the socket is quiet; loopback delivery can lag the sender slightly.
        rx.settimeout(DRAIN_TIMEOUT)
        packets = []
        while True:
            try:
                packets.append(rx.recv(65535))
            except OSError:  # includes TimeoutError
                break
    if len(packets) < MIN_PACKETS:
        raise CheckFailed(f"N1MM listener got {len(packets)} packets, expected >= {MIN_PACKETS}")
    for data in packets:
        try:
            root = ET.fromstring(data)
        except ET.ParseError as err:
            raise CheckFailed(f"invalid <Spectrum> XML: {err}") from None
        values = (root.findtext("SpectrumData") or "").split(",")
        if (
            root.tag != "Spectrum"
            or root.findtext("DataCount") != str(len(values))
            or len(values) != 850
        ):
            raise CheckFailed("packet does not match the N1MM <Spectrum> format")


GUI_SKIP = "skipped: no PySide6 wheels for free-threaded Python (--skip-gui)"


LIST_SCENARIOS = (
    "uv", "run", "python", "-c",
    "import json; from n1mm_scope_bridge.emulator import SCENARIOS; "
    "print(json.dumps({n: s.expect_error for n, s in SCENARIOS.items()}))",
)  # fmt: skip


def _collect(rx: socket.socket) -> list[bytes]:
    rx.settimeout(DRAIN_TIMEOUT)
    packets = []
    while True:
        try:
            packets.append(rx.recv(65535))
        except OSError:  # includes TimeoutError
            return packets


def emulator_scenarios(runner: Runner = run_command) -> None:
    """Run every emulator scenario through the real CLI (no radio needed)."""
    code, out = runner(LIST_SCENARIOS)
    if code != 0:
        raise CheckFailed(f"could not list emulator scenarios:\n{_tail(out)}")
    scenarios: dict[str, str] = json.loads(out.strip().splitlines()[-1])
    if not scenarios:
        raise CheckFailed("no emulator scenarios defined")
    failures = []
    for name, expect_error in sorted(scenarios.items()):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
            rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 21)
            rx.bind(("127.0.0.1", 0))
            cmd = ("uv", "run", "n1mm-scope-bridge", "run", "--scenario", name, "--duration", "2",
                   "--rate", "10", "--port", str(rx.getsockname()[1]))  # fmt: skip
            code, out = runner(cmd)
            packets = _collect(rx)
        if expect_error:
            if code != 1 or expect_error not in out:
                failures.append(f"{name}: expected exit 1 with {expect_error!r}, got {code}")
        elif code != 0 or len(packets) < MIN_PACKETS:
            failures.append(f"{name}: exit {code}, {len(packets)} packets\n{_tail(out, 5)}")
    if failures:
        raise CheckFailed("\n".join(failures))


def default_steps(runner: Runner = run_command, *, skip_gui: bool = False) -> list[Step]:
    sh = shutil.which("sh") or "sh"

    def build() -> None:
        shutil.rmtree(DIST, ignore_errors=True)
        code, out = runner(("uv", "build", "--out-dir", str(DIST)))
        if code != 0:
            raise CheckFailed(f"uv build failed ({code}):\n{_tail(out)}")

    return [
        Step(
            "Locked clean environment",
            (
                "uv",
                "sync",
                "--locked",
                "--reinstall",
                *(("--no-group", "gui-dev") if skip_gui else ()),
            ),
        ),
        Step("Lint (ruff)", ("uv", "run", "ruff", "check", ".")),
        Step("Format (ruff)", ("uv", "run", "ruff", "format", "--check", ".")),
        Step("Type check (mypy --strict)", ("uv", "run", "mypy")),
        Step(
            "Unit, slow, and licensing tests with coverage",
            (
                "uv",
                "run",
                "pytest",
                "--cov",
                "--cov-report=term-missing",
                "-p",
                "no:cacheprovider",
                *(("--cov-config=.coveragerc-nogui",) if skip_gui else ()),
            ),
        ),
        Step("Git and agent hook tests", (sh, "tests/hooks/run.sh")),
        Step("Build sdist and wheel", action=build),
        Step("Dist contents (licenses, source, no FTDI binaries)", action=check_dists),
        Step("Wheel installs and shows legal notices", action=lambda: wheel_smoke(runner=runner)),
        Step("End-to-end replay to N1MM UDP listener", action=lambda: e2e_replay(runner)),
        Step("Emulator scenarios through the CLI", action=lambda: emulator_scenarios(runner)),
        Step("Windows app (PyInstaller) runs", windows_only=True, disabled_reason="added by #6"),
        Step(
            "GUI self-test",
            windows_only=True,
            disabled_reason=GUI_SKIP if skip_gui else "added by #18",
        ),
        Step(
            "Installer silent install/run/uninstall",
            windows_only=True,
            disabled_reason="added by #20",
        ),
        Step("Website builds for this version", disabled_reason="added by #21"),
    ]


def environment() -> dict[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    return {
        "commit": commit or "unknown",
        "ref": os.environ.get("GITHUB_REF", "local"),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "date (UTC)": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    steps: Sequence[Step] | None = None,
    meta: dict[str, str] | None = None,
    runner: Runner = run_command,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--report", type=Path, default=ROOT / "regression-report.md")
    parser.add_argument(
        "--skip-gui",
        action="store_true",
        help="free-threaded Python jobs: no PySide6, so GUI checks are skipped",
    )
    parser.add_argument(
        "--skip-windows-only",
        action="store_true",
        help="for local runs off Windows; the result is not releasable",
    )
    args = parser.parse_args(argv)
    if args.skip_gui:
        # Every `uv run` re-syncs default groups; keep PySide6 out on free-threaded Python.
        os.environ["UV_NO_GROUP"] = "gui-dev"
    results = run_steps(
        steps if steps is not None else default_steps(runner, skip_gui=args.skip_gui),
        runner=runner,
        skip_windows_only=args.skip_windows_only,
    )
    # Steps disabled until their feature lands are allowed; skipped Windows steps are not.
    blocking_skips = [
        r
        for r in results
        if r.status == "SKIPPED" and not r.detail.startswith(("added by #", GUI_SKIP))
    ]
    ok = passed(results, allow_skips=True) and not blocking_skips
    report = render_report(results, meta if meta is not None else environment(), ok=ok)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    if blocking_skips:
        print("NOT RELEASABLE: Windows-only steps were skipped.", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
