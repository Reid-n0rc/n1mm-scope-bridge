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
DEFAULT_WIDTH = 640
GIF_COLOURS = 32  # keeps the GIF under the repo's 1 MiB file limit
MAX_GIF_BYTES = 1024 * 1024  # .githooks/pre-commit file-size limit
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


def write_animation(images: list[Image.Image], base: Path, fps: float) -> dict[str, int]:
    """Write ``base``.gif (shared palette, optimized), .webp and a static .png."""
    if not images:
        raise ValueError("no frames to write")
    duration = round(1000 / fps)
    palette = images[-1].quantize(colors=GIF_COLOURS, method=Image.Quantize.MEDIANCUT)
    frames = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]
    gif = base.with_suffix(".gif")
    frames[0].save(
        gif, save_all=True, append_images=frames[1:], duration=duration, loop=0, optimize=True,
        disposal=1,
    )  # fmt: skip
    webp = base.with_suffix(".webp")
    images[0].save(
        webp, save_all=True, append_images=images[1:], duration=duration, loop=0, quality=80,
        method=6,
    )  # fmt: skip
    png = base.with_suffix(".png")
    images[-1].save(png, optimize=True)
    return {p.suffix[1:]: p.stat().st_size for p in (gif, webp, png)}


def record(
    out_dir: Path,
    app: QApplication,
    feed: Feed | None = None,
    *,
    seconds: float = 6.0,
    fps: float = 4.0,
    settle: int = HISTORY_ROWS,
    width: int = DEFAULT_WIDTH,
    dark: bool = True,
) -> dict[str, object]:
    """Record the streaming window (light, and dark if asked); return the manifest entry."""
    if seconds <= 0 or fps <= 0:
        raise ValueError("--seconds and --fps must be greater than 0")
    feed = feed or emulator_feed()
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
        sizes["light"] = write_animation(images, out_dir / NAME, fps)
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
                sizes["dark"] = write_animation(dark_images, out_dir / f"{NAME}-dark", fps)
            finally:
                app.setPalette(original)
                refresh_stylesheet(app)
    finally:
        feed.stop()
        settings_path.unlink(missing_ok=True)
    entry: dict[str, object] = {
        "file": f"{NAME}.gif",
        "webp": f"{NAME}.webp",
        "still": f"{NAME}.png",
        "width": size[0],
        "height": size[1],
        "frames": steps,
        "fps": fps,
        "alt": f"{streaming_alt(source.status)} {source.note}",
        "caption": f"{LIVE_CAPTION} {source.note}",
        "animated": True,
        **({"simulated": True} if source.simulated else {"real_radio": True}),
        **(
            {
                "dark": f"{NAME}-dark.gif",
                "dark_webp": f"{NAME}-dark.webp",
                "dark_still": f"{NAME}-dark.png",
            }
            if "dark" in sizes
            else {}
        ),
        "bytes": sizes,
    }
    manifest_path = out_dir / MANIFEST
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    manifest[NAME] = entry
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return entry
