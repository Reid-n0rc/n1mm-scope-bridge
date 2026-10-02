# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Animated website recordings of the real GUI streaming (#124).

``record(out_dir, app, feed, ...)`` builds the real main window, primes the
waterfall with ``settle`` frames, then feeds one or more frames per output
step through the same handlers a live stream uses and grabs the window with
``QWidget.grab()``. Frames are written as a looping animated GIF (one shared
adaptive palette, Pillow's frame differencing) and an animated WebP, plus a
static PNG of the last frame for viewers who prefer reduced motion.

The default feed is the FT-710 emulator (deterministic, used in CI);
``radio_feed()`` reads the connected radio (receive only). Every recording
states its source in its manifest entry, alt text and caption.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import platform
import shutil
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from n1mm_scope_bridge.emulator import make_emulator
from n1mm_scope_bridge.gui.screenshot import (
    MANIFEST,
    SIMULATED_NOTE,
    ShotSource,
    band_name,
    demo_window,
    streaming_alt,
)
from n1mm_scope_bridge.gui.spectrum import HISTORY_ROWS
from n1mm_scope_bridge.gui.style import dark_palette, refresh_stylesheet
from n1mm_scope_bridge.pipeline import PipelineStats
from n1mm_scope_bridge.radios.base import ParsedFrame
from n1mm_scope_bridge.radios.ft710 import FT710
from n1mm_scope_bridge.transport.ft4222 import Ft4222Api, Ft4222Reader, load_api
from n1mm_scope_bridge.transport.replay import CaptureReader

NAME = "main-window-live"
DEFAULT_WIDTH = 800
GIF_WIDTH = 640
# GIF fallback sizes (width, colours), tried in order until it fits MAX_FILE_BYTES.
GIF_LADDER = ((GIF_WIDTH, 32), (560, 32), (480, 24), (400, 16), (320, 16))
GIF_MAX_FPS = 5.0
GIF_MAX_SECONDS = 6.0
MAX_FILE_BYTES = 1024 * 1024  # .githooks/pre-commit file-size limit
FORMATS = ("mp4", "webm", "gif")
# ffmpeg quality ladders, tried in order until a file fits MAX_FILE_BYTES.
MP4_CRF = (26, 30, 34, 38)
WEBM_CRF = (36, 42, 48, 54)
LIVE_CAPTION = "Live recording: the preview shows exactly what N1MM+ receives."


RADIO_FPS = 11.2  # measured on a real FT-710 (#111)


@dataclass(frozen=True)
class Feed:
    frames: Iterator[ParsedFrame]
    stop: Callable[[], object]
    note: str
    simulated: bool
    log_name: str
    source_fps: float = RADIO_FPS
    """Frames per second the source produces; recordings advance in real time."""


def _parsed(reader: Ft4222Reader) -> Iterator[ParsedFrame]:
    for raw in reader:
        yield FT710.parse(raw)


def emulator_feed() -> Feed:
    """Endless deterministic emulator frames (CI and default)."""
    reader = Ft4222Reader(make_emulator("steady", fps=0))
    return Feed(_parsed(reader), reader.stop, SIMULATED_NOTE, True, "FT-710 (emulator)")


def replay_feed(path: Path, recorded: dt.date | None = None) -> Feed:
    """Frames from a capture recorded from a real radio (``record``), paced as live."""
    reader = CaptureReader(path)
    if reader.model != FT710.model:
        raise ValueError(f"{path.name} was recorded from a {reader.model}, not a {FT710.model}")
    frames = (FT710.parse(raw) for raw in reader)
    first = next(frames, None)
    if first is None:
        raise ValueError(f"{path.name} has no frames")
    day = recorded or dt.date.fromtimestamp(path.stat().st_mtime)
    note = replay_note(first.status.vfo_hz, day)
    return Feed(itertools.chain([first], frames), reader.stop, note, False, "FT-710")


def replay_note(vfo_hz: int, day: dt.date) -> str:
    band = band_name(vfo_hz)
    where = f"{vfo_hz / 1e6:.3f} MHz" + (f" ({band})" if band else "")
    return (
        f"Live data from a real Yaesu FT-710 on {where}, recorded {day.isoformat()}, "
        "replayed from a capture."
    )


def radio_note(vfo_hz: int, today: dt.date, system: str | None = None) -> str:
    band = band_name(vfo_hz)
    mhz = f"{vfo_hz / 1e6:.3f} MHz"
    where = f"{band} ({mhz})" if band else mhz
    shown = system or {"Darwin": "macOS"}.get(platform.system(), platform.system())
    return f"Live recording of a real Yaesu FT-710 on {where}, {today.isoformat()}, on {shown}."


def radio_feed(
    lib_dir: str | None,
    *,
    api_loader: Callable[[str | None], Ft4222Api] = load_api,
    today: Callable[[], dt.date] = dt.date.today,
    system: str | None = None,
) -> Feed:
    """Live frames from the connected radio (receive only; nothing is sent to it)."""
    reader = Ft4222Reader(api_loader(lib_dir))
    frames = _parsed(reader)
    first = next(frames, None)
    if first is None:
        reader.stop()
        raise ValueError("the radio sent no scope frames")
    note = radio_note(first.status.vfo_hz, today(), system)
    return Feed(itertools.chain([first], frames), reader.stop, note, False, "FT-710")


def _to_pil(image: QImage) -> Image.Image:
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    data = bytes(rgb.constBits())
    size = (rgb.width(), rgb.height())
    return Image.frombuffer("RGB", size, data, "raw", "RGB", rgb.bytesPerLine(), 1).copy()


def _grab_frames(
    app: QApplication,
    feed: Feed,
    *,
    settle: int,
    steps: int,
    per_step: int,
    width: int,
    settings_path: Path,
) -> tuple[list[Image.Image], ShotSource]:
    primed = list(itertools.islice(feed.frames, settle))
    if not primed:
        raise ValueError("no frames to record")
    source = ShotSource(
        tuple(primed),
        primed[-1].status,
        PipelineStats(len(primed), 0, 0, max(1, len(primed) // 3)),
        feed.note,
        feed.simulated,
        log_name=feed.log_name,
    )
    window = demo_window(settings_path, source=source)
    images: list[Image.Image] = []
    try:
        window.show()
        app.processEvents()
        read = len(primed)
        for _ in range(steps):
            for frame in itertools.islice(feed.frames, per_step):
                read += 1
                window._on_frame(frame)
                window._on_status(frame.status)
            # Offscreen replay runs faster than real time: keep the card at the
            # configured N1MM+ rate instead of a wall-clock rate.
            window.model.stats = PipelineStats(read, 0, 0, max(1, read // 3))
            window.model.rate_per_s = window.settings.rate_hz
            window._refresh_status()
            app.processEvents()
            img = _to_pil(window.grab().toImage())
            if width and img.width != width:
                height = round(img.height * width / img.width)
                img = img.resize((width, height), Image.Resampling.LANCZOS)
            images.append(img)
    finally:
        window.quit_app()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    return images, source


def find_ffmpeg() -> str | None:
    """ffmpeg on PATH, else the binary from the optional imageio-ffmpeg package."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]  # noqa: PLC0415 - optional

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except (ImportError, RuntimeError):
        return None


Runner = Callable[..., "subprocess.CompletedProcess[bytes]"]


def _encode(
    ffmpeg: str, images: list[Image.Image], out: Path, fps: float, codec: list[str], run: Runner
) -> None:
    width, height = images[0].size
    cmd = [
        ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", f"{fps:g}", "-i", "-",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p", "-an",
        *codec, str(out),
    ]  # fmt: skip
    data = b"".join(im.convert("RGB").tobytes() for im in images)
    result = run(cmd, input=data, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed for {out.name}: {result.stderr.decode(errors='replace')}"
        )


def write_video(
    images: list[Image.Image],
    base: Path,
    fps: float,
    fmt: str,
    *,
    ffmpeg: str,
    run: Runner = subprocess.run,
) -> int:
    """Encode ``base``.mp4 (H.264) or .webm (VP9), lowering quality until it fits 1 MiB."""
    if not images:
        raise ValueError("no frames to write")
    out = base.with_suffix(f".{fmt}")
    ladder = MP4_CRF if fmt == "mp4" else WEBM_CRF
    for crf in ladder:
        if fmt == "mp4":
            codec = ["-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
                     "-movflags", "+faststart"]  # fmt: skip
        else:
            codec = ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(crf), "-row-mt", "1"]
        _encode(ffmpeg, images, out, fps, codec, run)
        if out.stat().st_size <= MAX_FILE_BYTES:
            return out.stat().st_size
    raise ValueError(f"{out.name} is over {MAX_FILE_BYTES} bytes even at the lowest quality")


def write_gif(images: list[Image.Image], base: Path, fps: float) -> int:
    """A lighter GIF fallback (at most GIF_MAX_FPS and GIF_MAX_SECONDS), shrunk until it
    fits MAX_FILE_BYTES."""
    if not images:
        raise ValueError("no frames to write")
    step = max(1, round(fps / GIF_MAX_FPS))
    gif_fps = fps / step
    picked = images[::step][: max(2, round(GIF_MAX_SECONDS * gif_fps))]
    gif = base.with_suffix(".gif")
    for width, colours in GIF_LADDER:
        frames = picked
        if frames[0].width > width:
            height = round(frames[0].height * width / frames[0].width)
            frames = [im.resize((width, height), Image.Resampling.LANCZOS) for im in frames]
        palette = frames[-1].quantize(colors=colours, method=Image.Quantize.MEDIANCUT)
        quantized = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in frames]
        quantized[0].save(
            gif, save_all=True, append_images=quantized[1:], duration=round(1000 / gif_fps),
            loop=0, optimize=True, disposal=1,
        )  # fmt: skip
        if gif.stat().st_size <= MAX_FILE_BYTES:
            return gif.stat().st_size
    raise ValueError(f"{gif.name} is over {MAX_FILE_BYTES} bytes even at the smallest size")


def write_animation(
    images: list[Image.Image],
    base: Path,
    fps: float,
    formats: tuple[str, ...] = FORMATS,
    *,
    ffmpeg: str | None = None,
    run: Runner = subprocess.run,
) -> dict[str, int]:
    """Write the requested formats plus a static ``base``.png; return their sizes."""
    if not images:
        raise ValueError("no frames to write")
    unknown = set(formats) - set(FORMATS)
    if unknown:
        raise ValueError(f"unknown format(s): {', '.join(sorted(unknown))}")
    sizes: dict[str, int] = {}
    videos = [f for f in formats if f in ("mp4", "webm")]
    if videos:
        exe = ffmpeg or find_ffmpeg()
        if exe is None:
            raise ValueError("MP4/WebM need ffmpeg on PATH (or pip install imageio-ffmpeg)")
        for fmt in videos:
            sizes[fmt] = write_video(images, base, fps, fmt, ffmpeg=exe, run=run)
    if "gif" in formats:
        sizes["gif"] = write_gif(images, base, fps)
    png = base.with_suffix(".png")
    images[-1].save(png, optimize=True)
    sizes["png"] = png.stat().st_size
    return sizes


def record(  # noqa: PLR0913 - keyword-only recording options
    out_dir: Path,
    app: QApplication,
    feed: Feed | None = None,
    *,
    seconds: float = 15.0,
    fps: float | None = None,
    formats: tuple[str, ...] = FORMATS,
    settle: int = HISTORY_ROWS,
    width: int = DEFAULT_WIDTH,
    dark: bool = True,
    ffmpeg: str | None = None,
    run: Runner = subprocess.run,
) -> dict[str, object]:
    """Record the streaming window (light, and dark if asked); return the manifest entry.

    ``fps`` defaults to the source's own frame rate, so every radio frame is a
    video frame and the waterfall scrolls smoothly.
    """
    feed = feed or emulator_feed()
    fps = feed.source_fps if fps is None else fps
    if seconds <= 0 or fps <= 0:
        raise ValueError("--seconds and --fps must be greater than 0")
    out_dir.mkdir(parents=True, exist_ok=True)
    steps = max(2, round(seconds * fps))
    per_step = max(1, round(feed.source_fps / fps))  # real-time waterfall speed
    settings_path = out_dir / "recording-settings.json"
    sizes: dict[str, dict[str, int]] = {}
    try:
        images, source = _grab_frames(
            app, feed, settle=settle, steps=steps, per_step=per_step, width=width,
            settings_path=settings_path,
        )  # fmt: skip
        sizes["light"] = write_animation(
            images, out_dir / NAME, fps, formats, ffmpeg=ffmpeg, run=run
        )
        size = images[0].size
        if dark:
            original = app.palette()
            app.setPalette(dark_palette())
            refresh_stylesheet(app)
            try:
                dark_images, _ = _grab_frames(
                    app, feed, settle=settle, steps=steps, per_step=per_step, width=width,
                    settings_path=settings_path,
                )  # fmt: skip
                sizes["dark"] = write_animation(
                    dark_images, out_dir / f"{NAME}-dark", fps, formats, ffmpeg=ffmpeg, run=run
                )
            finally:
                app.setPalette(original)
                refresh_stylesheet(app)
    finally:
        feed.stop()
        settings_path.unlink(missing_ok=True)
    still = f"{NAME}.png"
    entry: dict[str, object] = {
        "file": f"{NAME}.gif" if "gif" in formats else still,
        "still": still,
        "width": size[0],
        "height": size[1],
        "frames": steps,
        "fps": round(fps, 2),
        "alt": f"{streaming_alt(source.status)} {source.note}",
        "caption": f"{LIVE_CAPTION} {source.note}",
        "animated": True,
        **({"simulated": True} if source.simulated else {"real_radio": True}),
        **{fmt: f"{NAME}.{fmt}" for fmt in formats if fmt in ("mp4", "webm")},
        "bytes": sizes,
    }
    if "dark" in sizes:
        entry["dark_still"] = f"{NAME}-dark.png"
        if "gif" in formats:
            entry["dark"] = f"{NAME}-dark.gif"
        for fmt in ("mp4", "webm"):
            if fmt in formats:
                entry[f"dark_{fmt}"] = f"{NAME}-dark.{fmt}"
    manifest_path = out_dir / MANIFEST
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    manifest[NAME] = entry
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return entry
