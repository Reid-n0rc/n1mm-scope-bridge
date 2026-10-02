# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="GUI needs PySide6 (not available on free-threaded Python)")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from n1mm_scope_bridge.gui import app as gui_app
from n1mm_scope_bridge.gui import screenshot as ss

pytestmark = pytest.mark.gui


def test_capture_writes_every_scene_with_manifest(qtbot: QtBot, tmp_path: Path) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    paths = ss.capture(tmp_path, app, dark=lambda _a: False)
    expected = {f"{s.name}{suffix}.png" for s in ss.SCENES for suffix in ("", "-dark")}
    assert {p.name for p in paths} == expected
    manifest = json.loads((tmp_path / ss.MANIFEST).read_text(encoding="utf-8"))
    assert list(manifest) == [s.name for s in ss.SCENES]
    main = manifest["main-window"]
    image = QImage(str(tmp_path / "main-window.png"))
    assert (image.width(), image.height()) == (main["width"], main["height"])
    assert (main["width"], main["height"]) == ss.WINDOW_SIZE
    assert all(entry["alt"] and entry["caption"] for entry in manifest.values())
    # Streaming scenes show emulator data and must say so (honesty about the source).
    assert main["simulated"] is True
    assert ss.SIMULATED_NOTE in main["alt"]
    assert ss.SIMULATED_NOTE in main["caption"]
    assert "simulated" not in manifest["settings"]
    assert all(entry["dark"] == f"{name}-dark.png" for name, entry in manifest.items())
    light = QImage(str(tmp_path / "main-window.png")).pixelColor(4, 4).lightness()
    dark = QImage(str(tmp_path / "main-window-dark.png")).pixelColor(4, 4).lightness()
    assert dark < light  # the dark variant really is dark
    assert not (tmp_path / "screenshot-settings.json").exists()


def test_capture_is_deterministic(qtbot: QtBot, tmp_path: Path) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    ss.capture(tmp_path / "a", app, dark=lambda _a: False)
    ss.capture(tmp_path / "b", app, dark=lambda _a: False)
    for scene in ss.SCENES:
        a = QImage(str(tmp_path / "a" / f"{scene.name}.png"))
        b = QImage(str(tmp_path / "b" / f"{scene.name}.png"))
        assert a == b, scene.name


def test_demo_window_shows_streaming_state(qtbot: QtBot, tmp_path: Path) -> None:
    window = ss.demo_window(tmp_path / "s.json")
    qtbot.addWidget(window)
    assert window.chip.text() == "Streaming"
    assert window.status.text().startswith("Streaming to N1MM+")
    assert window.cards["frequency"].value.text() == "14.074 000 MHz"
    assert window.spectrum.rows_added == ss.WATERFALL_FRAMES
    assert "Started streaming" in window.log_view.toPlainText()
    assert window.tray is None
    window.quit_app()


def test_dark_supported_reports_platform_capability(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    assert isinstance(ss.dark_supported(app), bool)


def test_gui_main_screenshot_mode(
    qtbot: QtBot, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gui_app.main(["--screenshot", str(tmp_path)]) == 0
    assert f"Saved {2 * len(ss.SCENES)} screenshots" in capsys.readouterr().out
    assert (tmp_path / ss.MANIFEST).exists()


# --- real-radio source (#119) ----------------------------------------------------------------


class Ticks:
    """Fake monotonic clock: advances one second per call."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


def emulator_loader(_lib_dir: str | None) -> object:
    from n1mm_scope_bridge.emulator import make_emulator  # noqa: PLC0415

    return make_emulator("steady", fps=0)


def test_band_name() -> None:
    assert ss.band_name(7_074_000) == "40 m"
    assert ss.band_name(14_074_000) == "20 m"
    assert ss.band_name(50_313_000) == "6 m"
    assert ss.band_name(10_000_000) == ""


def test_radio_source_reads_frames_and_labels_them_real() -> None:
    import datetime as dt  # noqa: PLC0415

    source = ss.radio_source(
        None,
        5.0,
        api_loader=emulator_loader,  # type: ignore[arg-type]
        clock=Ticks(),
        today=lambda: dt.date(2026, 10, 2),
        system="Windows",
    )
    assert not source.simulated
    assert 1 <= len(source.frames) <= ss.WATERFALL_FRAMES
    assert source.status.vfo_hz == 14_074_000
    assert source.note == "Real Yaesu FT-710 on 20 m (14.074 MHz), captured 2026-10-02 on Windows."
    assert source.stats.frames_read >= len(source.frames)
    assert source.log_name == "FT-710"


def test_radio_source_outside_a_band_and_default_platform() -> None:
    from n1mm_scope_bridge.emulator import RadioState  # noqa: PLC0415
    from n1mm_scope_bridge.emulator.ft710 import Ft710Emulator  # noqa: PLC0415

    def loader(_d: str | None) -> object:
        return Ft710Emulator(RadioState(vfo_a_hz=10_000_000))

    source = ss.radio_source(None, 1.0, api_loader=loader, clock=Ticks())  # type: ignore[arg-type]
    assert "on 10.000 MHz, captured" in source.note


@pytest.mark.parametrize("settle", [0.0, -1.0])
def test_radio_source_needs_positive_settle(settle: float) -> None:
    with pytest.raises(ValueError, match="--settle"):
        ss.radio_source(None, settle, api_loader=emulator_loader)  # type: ignore[arg-type]


def test_radio_source_reports_no_frames() -> None:
    from fakes import FakeApi  # noqa: PLC0415

    def loader(_d: str | None) -> object:
        return FakeApi(b"")  # opens, then no data: reader gives up

    from n1mm_scope_bridge.transport.ft4222 import Ft4222Error  # noqa: PLC0415

    with pytest.raises((ValueError, Ft4222Error)):
        ss.radio_source(None, 1.0, api_loader=loader, clock=Ticks())  # type: ignore[arg-type]


def test_capture_with_real_source_saves_only_the_streaming_window(
    qtbot: QtBot, tmp_path: Path
) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    source = ss.radio_source(None, 3.0, api_loader=emulator_loader, clock=Ticks())  # type: ignore[arg-type]
    paths = ss.capture(tmp_path, app, dark=lambda _a: False, source=source)
    assert {p.name for p in paths} == {"main-window.png", "main-window-dark.png"}
    manifest = json.loads((tmp_path / ss.MANIFEST).read_text(encoding="utf-8"))
    assert list(manifest) == ["main-window"]
    main = manifest["main-window"]
    assert main["real_radio"] is True
    assert "simulated" not in main
    assert source.note in main["alt"]
    assert source.note in main["caption"]
    assert ss.SIMULATED_NOTE not in main["caption"]


def test_app_screenshot_radio_source_error_exits_1(
    qtbot: QtBot, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "no-ftdi-here"
    code = gui_app.main(
        ["--screenshot", str(tmp_path / "s"), "--source", "radio", "--ftdi-lib-dir", str(missing)]
    )
    assert code == 1
    assert "error:" in capsys.readouterr().err


def test_app_screenshot_radio_source_success(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ss.radio_source(None, 2.0, api_loader=emulator_loader, clock=Ticks())  # type: ignore[arg-type]
    monkeypatch.setattr(ss, "radio_source", lambda _d, _s: real)
    assert gui_app.main(["--screenshot", str(tmp_path / "s"), "--source", "radio"]) == 0
    assert (tmp_path / "s" / "main-window.png").exists()
