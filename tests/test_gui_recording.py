# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Animated website recordings of the GUI (#124), recorded from the emulator."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="GUI needs PySide6 (not available on free-threaded Python)")
Image = pytest.importorskip("PIL.Image")

from fakes import FakeApi  # noqa: E402
from frames import make_ft4222_frame  # noqa: E402
from pytestqt.qtbot import QtBot  # noqa: E402

from n1mm_scope_bridge.gui import app as gui_app  # noqa: E402
from n1mm_scope_bridge.gui import recording as rec  # noqa: E402

pytestmark = pytest.mark.gui


def record_small(tmp_path: Path, qtbot: QtBot, **kw: object) -> dict[str, object]:
    del qtbot  # ensures a QApplication exists
    app = gui_app.application()
    return rec.record(tmp_path, app, seconds=1.0, fps=4.0, settle=20, width=320, **kw)  # type: ignore[arg-type]


def test_records_animated_gif_webp_and_still(tmp_path: Path, qtbot: QtBot) -> None:
    entry = record_small(tmp_path, qtbot)
    gif = Image.open(tmp_path / "main-window-live.gif")
    assert gif.is_animated
    assert gif.n_frames == entry["frames"] == 4
    assert gif.info["loop"] == 0
    assert gif.size[0] == 320
    webp = Image.open(tmp_path / "main-window-live.webp")
    assert webp.is_animated
    still = Image.open(tmp_path / "main-window-live.png")
    assert still.size == gif.size
    assert (tmp_path / "main-window-live-dark.gif").exists()
    assert entry["simulated"] is True
    assert "emulator" in str(entry["caption"])
    assert entry["still"] == "main-window-live.png"
    assert entry["dark_still"] == "main-window-live-dark.png"
    sizes = entry["bytes"]
    assert isinstance(sizes, dict)
    assert sizes["light"]["gif"] < rec.MAX_GIF_BYTES
    assert not (tmp_path / "recording-settings.json").exists()


def test_frames_change_over_time(tmp_path: Path, qtbot: QtBot) -> None:
    record_small(tmp_path, qtbot, dark=False)
    gif = Image.open(tmp_path / "main-window-live.gif")
    first = gif.convert("RGB").tobytes()
    gif.seek(gif.n_frames - 1)
    assert gif.convert("RGB").tobytes() != first  # the waterfall moves


def test_manifest_entry_is_merged(tmp_path: Path, qtbot: QtBot) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"settings": {"file": "s.png"}}))
    record_small(tmp_path, qtbot, dark=False)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert set(manifest) == {"settings", "main-window-live"}
    assert manifest["main-window-live"]["animated"] is True
    assert "dark" not in manifest["main-window-live"]


@pytest.mark.parametrize(("seconds", "fps"), [(0.0, 8.0), (2.0, 0.0)])
def test_rejects_bad_timing(tmp_path: Path, qtbot: QtBot, seconds: float, fps: float) -> None:
    del qtbot
    with pytest.raises(ValueError, match="greater than 0"):
        rec.record(tmp_path, gui_app.application(), seconds=seconds, fps=fps)


def test_write_animation_needs_frames(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no frames"):
        rec.write_animation([], tmp_path / "x", 8.0)


def test_radio_feed_labels_the_real_radio(tmp_path: Path, qtbot: QtBot) -> None:
    api = FakeApi(repeat=make_ft4222_frame(vfo_a_hz=7_074_000, span_index=3))
    feed = rec.radio_feed(
        None, api_loader=lambda _d: api, today=lambda: dt.date(2026, 10, 2), system="macOS"
    )
    assert feed.simulated is False
    assert (
        feed.note
        == "Live recording of a real Yaesu FT-710 on 40 m (7.074 MHz), 2026-10-02, on macOS."
    )
    del qtbot
    entry = rec.record(
        tmp_path, gui_app.application(), feed, seconds=0.5, fps=4.0, settle=5, width=240, dark=False
    )
    assert entry["real_radio"] is True
    assert "simulated" not in entry


def test_radio_feed_with_no_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rec, "_parsed", lambda _reader: iter(()))
    with pytest.raises(ValueError, match="no scope frames"):
        rec.radio_feed(None, api_loader=lambda _d: FakeApi())


def test_radio_note_outside_bands() -> None:
    note = rec.radio_note(5_000_000, dt.date(2026, 1, 1), "Windows")
    assert note == "Live recording of a real Yaesu FT-710 on 5.000 MHz, 2026-01-01, on Windows."


def test_record_flag_end_to_end(
    tmp_path: Path, qtbot: QtBot, capsys: pytest.CaptureFixture[str]
) -> None:
    del qtbot
    code = gui_app.main(["--record", str(tmp_path), "--seconds", "0.5", "--fps", "4"])
    assert code == 0
    assert "Saved main-window-live.gif" in capsys.readouterr().out
    assert (tmp_path / "main-window-live.gif").exists()


def test_record_flag_reports_errors(
    tmp_path: Path, qtbot: QtBot, capsys: pytest.CaptureFixture[str]
) -> None:
    del qtbot
    assert gui_app.main(["--record", str(tmp_path), "--seconds", "0"]) == 1
    assert "error:" in capsys.readouterr().err
