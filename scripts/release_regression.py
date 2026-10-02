# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Full release regression for release candidates and releases (issue #16).

Runs every check a release must pass, in order, stops at the first failure,
and writes a Markdown report. Standard library only, so it can run with any
Python before the project environment exists:

    uv run --no-project python scripts/release_regression.py --report regression-report.md

The checks themselves live in scripts/regression_steps/NN_name.py, one file
per check, loaded in filename order (#45). Every new user-facing feature adds
its own step file (AGENTS.md); this runner does not change.

Windows-only steps (app, installer, GUI) are skipped with --skip-windows-only
and marked SKIPPED in the report. A release requires a Windows run with no
skips.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType

from regression_core import (
    GUI_SKIP,
    PENDING,
    ROOT,
    CheckFailed,
    Result,
    Runner,
    Step,
    StepContext,
    run_command,
    tail,
)

__all__ = ["CheckFailed", "Result", "Runner", "Step", "StepContext", "default_steps", "main"]

STEPS_DIR = Path(__file__).resolve().parent / "regression_steps"


def load_step_files(directory: Path = STEPS_DIR) -> list[ModuleType]:
    """Import every ``NN_name.py`` step file in ``directory``, in filename order."""
    modules: list[ModuleType] = []
    for path in sorted(directory.glob("[0-9]*.py")):
        spec = importlib.util.spec_from_file_location(f"regression_steps.{path.stem}", path)
        if spec is None or spec.loader is None:  # pragma: no cover - not a loadable file
            raise RuntimeError(f"cannot load regression step file {path.name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not callable(getattr(module, "steps", None)):
            raise RuntimeError(f"regression step file {path.name} has no steps(ctx) function")
        modules.append(module)
    return modules


def default_steps(
    runner: Runner = run_command, *, skip_gui: bool = False, directory: Path = STEPS_DIR
) -> list[Step]:
    ctx = StepContext(runner=runner, skip_gui=skip_gui)
    return [step for module in load_step_files(directory) for step in module.steps(ctx)]


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
            detail = "" if code == 0 else f"exit code {code}\n{tail(output)}"
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
    parser.add_argument(
        "--portable",
        action="store_true",
        help="CI portability job off Windows: skip Windows-only steps and pass if the rest "
        "pass (the report says it is not releasable)",
    )
    args = parser.parse_args(argv)
    if args.portable:
        args.skip_windows_only = True
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
        r for r in results if r.status == "SKIPPED" and not r.detail.startswith((PENDING, GUI_SKIP))
    ]
    ok = passed(results, allow_skips=True) and (args.portable or not blocking_skips)
    meta = dict(meta if meta is not None else environment())
    if args.portable:
        meta["scope"] = "portable subset (Windows-only steps skipped; not releasable)"
    report = render_report(results, meta, ok=ok)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    if blocking_skips:
        print("NOT RELEASABLE: Windows-only steps were skipped.", file=sys.stderr)
        if args.portable:
            print("(--portable: allowed for this portability job)", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
