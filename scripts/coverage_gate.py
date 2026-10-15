# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Per-area coverage floors (issue #180).

Coverage measures both the app package and ``scripts/``. One combined floor
would let well-tested tooling hide gaps in the app, so each area has its own:

    uv run python scripts/coverage_gate.py            # after a pytest --cov run
    uv run python scripts/coverage_gate.py --config .coveragerc-nogui

The scripts floor is a ratchet: raise it when coverage improves, never lower it.
"""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Callable, Mapping, Sequence

AREAS: dict[str, str] = {
    "app": "*/n1mm_scope_bridge/*",
    "scripts": "*/scripts/*",
}
# scripts: lowest CI job was 98.69% when the gate landed (#180); ratchet only upward.
FLOORS: dict[str, float] = {"app": 90.0, "scripts": 98.0}

Report = Callable[[str], float | None]


def check(report: Report, floors: Mapping[str, float]) -> list[str]:
    """Problems for every area below its floor (or with no measured files)."""
    problems = []
    for area, floor in floors.items():
        pct = report(AREAS[area])
        if pct is None:
            problems.append(f"{area}: no coverage data (pattern {AREAS[area]})")
        elif pct < floor:
            problems.append(f"{area}: {pct:.1f}% is below the {floor:g}% floor")
    return problems


def coverage_report(config: str | bool) -> Report:  # pragma: no cover - needs a coverage data file
    import coverage  # noqa: PLC0415 - dev-only dependency, imported when actually gating
    from coverage.exceptions import NoDataError  # noqa: PLC0415

    cov = coverage.Coverage(config_file=config)
    cov.load()

    def report(pattern: str) -> float | None:
        try:
            return float(cov.report(include=[pattern], file=io.StringIO()))
        except NoDataError:
            return None

    return report


def main(argv: Sequence[str] | None = None, *, report: Report | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--config", default=True, help="coverage config file (default: pyproject)")
    args = parser.parse_args(argv)
    problems = check(report or coverage_report(args.config), FLOORS)
    for problem in problems:
        print(f"coverage gate: {problem}", file=sys.stderr)
    if not problems:
        print("coverage gate: " + ", ".join(f"{a} >= {f:g}%" for a, f in FLOORS.items()) + " OK")
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
