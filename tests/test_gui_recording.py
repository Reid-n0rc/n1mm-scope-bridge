# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Animated website recordings of the GUI (#124), recorded from the emulator."""

from __future__ import annotations

import datetime as dt
import json
import random
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
    kw.setdefault("formats", ("gif",))
    return rec.record(tmp_path, app, seconds=1.0, fps=4.0, settle=20, width=320, **kw)  # type: ignore[arg-type]


def test_records_animated_gif_and_still(tmp_path: Path, qtbot: QtBot) -> None:
    entry = record_small(tmp_path, qtbot)
    gif = Image.open(tmp_path / "main-window-live.gif")
    assert gif.is_animated
    assert gif.n_frames == entry["frames"] == 4
    assert gif.info["loop"] == 0
    assert gif.size[0] == 320
    assert "mp4" not in entry
    still = Image.open(tmp_path / "main-window-live.png")
    assert still.size == gif.size
    assert (tmp_path / "main-window-live-dark.gif").exists()
    assert entry["simulated"] is True
    assert "emulator" in str(entry["caption"])
    assert entry["still"] == "main-window-live.png"
    assert entry["dark_still"] == "main-window-live-dark.png"
    sizes = entry["bytes"]
    assert isinstance(sizes, dict)
    assert sizes["light"]["gif"] < rec.MAX_FILE_BYTES
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
        tmp_path, gui_app.application(), feed, seconds=0.5, fps=4.0, settle=5, width=240,
        dark=False, formats=("gif",),
    )  # fmt: skip
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
    code = gui_app.main(
        ["--record", str(tmp_path), "--seconds", "0.5", "--fps", "4", "--format", "gif"]
    )
    assert code == 0
    assert "Saved main-window-live.gif" in capsys.readouterr().out
    assert (tmp_path / "main-window-live.gif").exists()


def test_record_flag_reports_errors(
    tmp_path: Path, qtbot: QtBot, capsys: pytest.CaptureFixture[str]
) -> None:
    del qtbot
    code = gui_app.main(["--record", str(tmp_path), "--seconds", "0"])
    assert code == 1
    assert "error:" in capsys.readouterr().err


# --- video output (#126) ------------------------------------------------------------


def frames(n: int = 4, size: tuple[int, int] = (64, 48)) -> list[object]:
    return [Image.new("RGB", size, (i * 40 % 256, 20, 60)) for i in range(n)]


class FakeFfmpeg:
    """Records ffmpeg command lines and writes an output file of a chosen size per call."""

    def __init__(self, sizes: list[int], code: int = 0) -> None:
        self.sizes = sizes
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kw: object) -> object:
        self.calls.append(cmd)
        assert isinstance(kw["input"], bytes)
        size = self.sizes[min(len(self.calls) - 1, len(self.sizes) - 1)]
        Path(cmd[-1]).write_bytes(b"\0" * size)

        class Result:
            returncode = self.code
            stderr = b"boom"

        return Result()


def test_write_video_mp4_command(tmp_path: Path) -> None:
    fake = FakeFfmpeg([1000])
    size = rec.write_video(frames(), tmp_path / "v", 11.2, "mp4", ffmpeg="ffmpeg", run=fake)  # type: ignore[arg-type]
    assert size == 1000
    cmd = fake.calls[0]
    assert cmd[:2] == ["ffmpeg", "-y"]
    assert "libx264" in cmd
    assert "+faststart" in cmd
    assert "yuv420p" in cmd
    assert cmd[cmd.index("-r") + 1] == "11.2"
    assert cmd[cmd.index("-s") + 1] == "64x48"
    assert cmd[-1].endswith("v.mp4")


def test_write_video_lowers_quality_until_it_fits(tmp_path: Path) -> None:
    big = rec.MAX_FILE_BYTES + 1
    fake = FakeFfmpeg([big, big, 500])
    size = rec.write_video(frames(), tmp_path / "v", 10, "webm", ffmpeg="ffmpeg", run=fake)  # type: ignore[arg-type]
    assert size == 500
    crfs = [c[c.index("-crf") + 1] for c in fake.calls]
    assert crfs == [str(x) for x in rec.WEBM_CRF[:3]]
    assert "libvpx-vp9" in fake.calls[0]


def test_write_video_gives_up_when_too_big(tmp_path: Path) -> None:
    fake = FakeFfmpeg([rec.MAX_FILE_BYTES + 1])
    with pytest.raises(ValueError, match="over"):
        rec.write_video(frames(), tmp_path / "v", 10, "mp4", ffmpeg="ffmpeg", run=fake)  # type: ignore[arg-type]
    assert len(fake.calls) == len(rec.MP4_CRF)


def test_write_video_reports_ffmpeg_failure(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"ffmpeg failed.*boom"):
        rec.write_video(frames(), tmp_path / "v", 10, "mp4", ffmpeg="ff", run=FakeFfmpeg([1], 1))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="no frames"):
        rec.write_video([], tmp_path / "v", 10, "mp4", ffmpeg="ff")


def test_write_gif_fallback_is_capped(tmp_path: Path) -> None:
    size = rec.write_gif(frames(200, (800, 400)), tmp_path / "g", 11.2)  # type: ignore[arg-type]
    gif = Image.open(tmp_path / "g.gif")
    assert size < rec.MAX_FILE_BYTES
    assert gif.width == rec.GIF_WIDTH
    assert gif.n_frames <= rec.GIF_MAX_SECONDS * rec.GIF_MAX_FPS + 1
    with pytest.raises(ValueError, match="no frames"):
        rec.write_gif([], tmp_path / "g", 10)


def test_write_animation_formats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeFfmpeg([100])
    sizes = rec.write_animation(frames(), tmp_path / "a", 10, ("mp4", "gif"), ffmpeg="ff", run=fake)  # type: ignore[arg-type]
    assert set(sizes) == {"mp4", "gif", "png"}
    with pytest.raises(ValueError, match="unknown format"):
        rec.write_animation(frames(), tmp_path / "a", 10, ("avi",))  # type: ignore[arg-type]
    monkeypatch.setattr(rec, "find_ffmpeg", lambda: None)
    with pytest.raises(ValueError, match="need ffmpeg"):
        rec.write_animation(frames(), tmp_path / "a", 10, ("webm",))  # type: ignore[arg-type]


def test_find_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/ffmpeg")
    assert rec.find_ffmpeg() == "/usr/bin/ffmpeg"
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setitem(__import__("sys").modules, "imageio_ffmpeg", None)
    assert rec.find_ffmpeg() is None


def test_record_defaults_to_source_rate_with_video(tmp_path: Path, qtbot: QtBot) -> None:
    del qtbot
    fake = FakeFfmpeg([2000])
    entry = rec.record(
        tmp_path,
        gui_app.application(),
        seconds=1.0,
        settle=5,
        width=200,
        ffmpeg="ff",
        run=fake,  # type: ignore[arg-type]
    )
    assert entry["fps"] == round(rec.RADIO_FPS, 2)
    assert entry["frames"] == round(rec.RADIO_FPS)
    assert entry["mp4"] == "main-window-live.mp4"
    assert entry["webm"] == "main-window-live.webm"
    assert entry["dark_mp4"] == "main-window-live-dark.mp4"
    assert entry["dark_webm"] == "main-window-live-dark.webm"
    assert entry["file"] == "main-window-live.gif"
    assert len(fake.calls) == 4  # mp4 + webm, light + dark


@pytest.mark.skipif(rec.find_ffmpeg() is None, reason="ffmpeg not installed")
def test_real_ffmpeg_encodes_playable_files(tmp_path: Path) -> None:
    imgs = frames(12, (120, 80))
    sizes = rec.write_animation(imgs, tmp_path / "r", 11.2, ("mp4", "webm"))  # type: ignore[arg-type]
    assert sizes["mp4"] > 0
    assert sizes["webm"] > 0
    assert (tmp_path / "r.mp4").read_bytes()[4:8] == b"ftyp"
    assert (tmp_path / "r.webm").read_bytes()[:4] == b"\x1a\x45\xdf\xa3"


def test_write_gif_shrinks_until_it_fits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:

    rng = random.Random(1)
    noisy = [Image.frombytes("RGB", (700, 300), rng.randbytes(700 * 300 * 3)) for _ in range(6)]
    monkeypatch.setattr(rec, "MAX_FILE_BYTES", 400_000)
    size = rec.write_gif(noisy, tmp_path / "n", 5)
    assert size <= 400_000
    with Image.open(tmp_path / "n.gif") as shrunk:
        width = shrunk.width
    assert width < rec.GIF_WIDTH
    monkeypatch.setattr(rec, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError, match="smallest size"):
        rec.write_gif(noisy, tmp_path / "n", 5)
