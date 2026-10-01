# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Helpers shared by the per-command CLI tests in tests/cli/."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from fakes import FakeApi

from n1mm_scope_bridge.cli import main
from n1mm_scope_bridge.transport.ft4222 import LibraryNotFound

FIXTURE = Path(__file__).parent / "fixtures" / "ft710_synthetic.cap"


def cli(*argv: str, api: FakeApi | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()

    def loader(lib_dir: str | None) -> Any:
        if api is None:
            raise LibraryNotFound("Could not load FTDI's LibFT4222/D2XX libraries")
        return api

    code = main(list(argv), api_loader=loader, out=out, err=err)
    return code, out.getvalue(), err.getvalue()
