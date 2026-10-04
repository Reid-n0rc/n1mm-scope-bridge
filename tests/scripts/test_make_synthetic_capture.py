# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

from pathlib import Path

import make_synthetic_capture as msc
import pytest

from n1mm_scope_bridge.transport.replay import CaptureReader


def test_main_writes_a_readable_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "sub" / "synthetic.cap"
    monkeypatch.setattr(msc, "OUT", out)
    msc.main()
    assert len(list(CaptureReader(out))) == msc.FRAMES
    assert f"({msc.FRAMES} frames)" in capsys.readouterr().out


def test_committed_fixture_matches_generator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "synthetic.cap"
    monkeypatch.setattr(msc, "OUT", out)
    msc.main()
    committed = Path(__file__).resolve().parents[1] / "fixtures" / "ft710_synthetic.cap"
    assert out.read_bytes() == committed.read_bytes()
