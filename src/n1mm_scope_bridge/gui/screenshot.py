# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Website screenshots of the real GUI (#68, part of #22; real radio: #119).

``capture(out_dir)`` builds the actual window and dialogs, fills them with
data from a ``ShotSource`` and fixed log timestamps, and saves PNGs with
``QWidget.grab()`` plus a ``manifest.json`` (file names, pixel sizes, alt text)
that ``scripts/build_site.py`` reads. Works offscreen.

The default source is the built-in FT-710 emulator (deterministic, used in
CI). ``radio_source()`` reads real frames from a connected radio instead
(receive only), and only the streaming main window is captured from it.
Every streaming screenshot states its source in its alt text and caption.
"""

from __future__ import annotations

import datetime as dt
import json
import platform
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget

from n1mm_scope_bridge.emulator import make_emulator
from n1mm_scope_bridge.gui.main_window import DEFAULT_SIZE, MainWindow
from n1mm_scope_bridge.gui.spectrum import HISTORY_ROWS
from n1mm_scope_bridge.gui.status import LogBuffer
from n1mm_scope_bridge.gui.style import dark_palette, refresh_stylesheet
from n1mm_scope_bridge.gui.tray import build_close_box
from n1mm_scope_bridge.pipeline import PipelineStats
from n1mm_scope_bridge.radios.base import ParsedFrame, ScopeStatus
from n1mm_scope_bridge.radios.ft710 import FT710
from n1mm_scope_bridge.settings import Settings
from n1mm_scope_bridge.transport.ft4222 import Ft4222Api, Ft4222Reader, load_api

WINDOW_SIZE = DEFAULT_SIZE
WATERFALL_FRAMES = HISTORY_ROWS  # history fills the waterfall
DEMO_TIME = 1_790_000_000.0  # fixed log timestamps
DEMO_STATUS = ScopeStatus(14_074_000, 20_000, "center", "Center (Normal)")
DEMO_STATS = PipelineStats(frames_read=4_120, frames_dropped=0, bad_frames=0, emitted=824)
FTDI_ERROR = (
    "Could not load FTDI's LibFT4222/D2XX libraries. "
    "Install them from FTDI, or set the FTDI library folder."
)
MANIFEST = "manifest.json"

# Emulator streaming screenshots say so in their alt text and caption.
SIMULATED_NOTE = "Simulated signals from the built-in FT-710 emulator, not a real radio."
BANDS = (
    (1_800_000, 2_000_000, "160 m"),
    (3_500_000, 4_000_000, "80 m"),
    (5_330_000, 5_410_000, "60 m"),
    (7_000_000, 7_300_000, "40 m"),
    (10_100_000, 10_150_000, "30 m"),
    (14_000_000, 14_350_000, "20 m"),
    (18_068_000, 18_168_000, "17 m"),
    (21_000_000, 21_450_000, "15 m"),
    (24_890_000, 24_990_000, "12 m"),
    (28_000_000, 29_700_000, "10 m"),
    (50_000_000, 54_000_000, "6 m"),
)


def band_name(hz: int) -> str:
    """Amateur band for a frequency, or "" outside the HF and 6 m bands."""
    return next((name for lo, hi, name in BANDS if lo <= hz <= hi), "")


@dataclass(frozen=True)
class ShotSource:
    """Where the streaming screenshot's data comes from, and how it is labelled."""

    frames: tuple[ParsedFrame, ...]
    status: ScopeStatus
    stats: PipelineStats
    note: str
    """Appended to the streaming scene's alt text and caption (states the source)."""
    simulated: bool
    log_name: str = "FT-710 (emulator)"


@dataclass(frozen=True)
class Scene:
    name: str
    alt: str
    caption: str
    streaming: bool = False
    """True when the image shows spectrum data; its alt text comes from the source."""


def streaming_alt(status: ScopeStatus) -> str:
    return (
        "The N1MM Scope Bridge window streaming a Yaesu FT-710 on "
        f"{status.vfo_hz / 1e6:.3f} MHz to N1MM+: a live spectrum and waterfall, cards for "
        "frequency, span, scope mode, N1MM+ rate and health, and the Start/Stop button."
    )


SCENES = (
    Scene(
        "main-window",
        "",
        "Streaming: the preview shows exactly what N1MM+ receives.",
        streaming=True,
    ),
    Scene(
        "main-window-idle",
        "The N1MM Scope Bridge window before streaming, inviting you to press Start or to "
        "try the built-in emulator.",
        "Before you press Start.",
    ),
    Scene(
        "settings",
        "The Settings dialog with pages for Radio, N1MM+, Display, Startup and closing, "
        "and Advanced; the Radio page shows the radio model, the emulator option, and the "
        "FTDI library folder.",
        "Settings are grouped into pages and save automatically.",
    ),
    Scene(
        "close-prompt",
        "The close prompt asking whether to keep streaming in the system tray or exit, "
        "with a Remember my choice check box.",
        "Closing the window asks whether to keep streaming in the system tray or exit.",
    ),
    Scene(
        "ftdi-error",
        "An error dialog saying FTDI's LibFT4222 libraries could not be loaded, "
        "with an Open FTDI download page button.",
        "If FTDI's library is missing, the bridge says so and links to FTDI's download page.",
    ),
)


def demo_frames(count: int = WATERFALL_FRAMES) -> list[ParsedFrame]:
    """Parsed frames from the FT-710 emulator (deterministic seed)."""
    reader = Ft4222Reader(make_emulator("steady", fps=0))
    frames: list[ParsedFrame] = []
    for raw in reader:
        frames.append(FT710.parse(raw))
        if len(frames) >= count:
            reader.stop()
    return frames


def emulator_source() -> ShotSource:
    """Deterministic emulator data (the CI and default source)."""
    return ShotSource(tuple(demo_frames()), DEMO_STATUS, DEMO_STATS, SIMULATED_NOTE, True)


def radio_source(
    lib_dir: str | None,
    settle_s: float,
    *,
    api_loader: Callable[[str | None], Ft4222Api] = load_api,
    clock: Callable[[], float] = time.monotonic,
    today: Callable[[], dt.date] = dt.date.today,
    system: str | None = None,
) -> ShotSource:
    """Read real frames from the connected radio for ``settle_s`` seconds (receive only).

    Keeps the last ``WATERFALL_FRAMES`` frames so the waterfall shows real
    signals. Raises ``ValueError`` if the radio sent nothing usable.
    """
    if settle_s <= 0:
        raise ValueError("--settle must be greater than 0 seconds")
    reader = Ft4222Reader(api_loader(lib_dir))
    frames: list[ParsedFrame] = []
    read = 0
    deadline = clock() + settle_s
    for raw in reader:
        read += 1
        frames = [*frames[-(WATERFALL_FRAMES - 1) :], FT710.parse(raw)]
        if clock() >= deadline:
            reader.stop()
    if not frames:
        raise ValueError("the radio sent no scope frames")
    status = frames[-1].status
    band = band_name(status.vfo_hz)
    mhz = f"{status.vfo_hz / 1e6:.3f} MHz"
    where = f"{band} ({mhz})" if band else mhz
    shown = system or {"Darwin": "macOS"}.get(platform.system(), platform.system())
    note = f"Real Yaesu FT-710 on {where}, captured {today().isoformat()} on {shown}."
    stats = PipelineStats(
        frames_read=read, frames_dropped=0, bad_frames=0, emitted=round(settle_s * 4)
    )
    return ShotSource(tuple(frames), status, stats, note, simulated=False, log_name="FT-710")


def demo_window(
    settings_path: Path, *, streaming: bool = True, source: ShotSource | None = None
) -> MainWindow:
    """The real main window in a fixed state, without starting a stream."""
    source = source or emulator_source()
    window = MainWindow(
        Settings(emulator=source.simulated),
        settings_path=settings_path,
        save=lambda _s, _p: None,
        open_url=lambda _u: None,
        tray_available=lambda: False,
        ask=lambda: ("cancel", False),
    )
    window.log = LogBuffer(now=lambda: DEMO_TIME)
    window.log_view.clear()
    # Site media always show the waterfall, even though the preview is off by default.
    window.set_preview_visible(True, persist=False)
    if streaming:
        st = source.status
        window.model.started()
        window.model.status = st
        window.model.stats = source.stats
        window.model.rate_per_s = 4.0
        for frame in source.frames:
            window.spectrum.set_frame(frame.spectrum, window.settings.scaling)
        window._set_state("streaming", window._streaming_message())
        window._log("info", f"Started streaming {source.log_name} to N1MM+ at 127.0.0.1:13064")
        window._log(
            "info",
            f"Scope: {st.vfo_hz / 1e6:.6f} MHz, span {st.span_hz / 1e3:g} kHz, {st.mode_name}",
        )
    window.resize(*WINDOW_SIZE)
    return window


def _grab(widget: QWidget, app: QApplication, path: Path) -> tuple[int, int]:
    widget.show()
    app.processEvents()
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(path), "PNG"):
        raise OSError(f"could not save screenshot {path}")
    return pixmap.width(), pixmap.height()


def _capture_theme(
    app: QApplication, out_dir: Path, suffix: str, source: ShotSource, names: Sequence[str]
) -> dict[str, tuple[int, int]]:
    sizes: dict[str, tuple[int, int]] = {}
    window = demo_window(out_dir / "screenshot-settings.json", source=source)
    idle = demo_window(out_dir / "screenshot-settings.json", streaming=False, source=source)
    widgets: list[QWidget] = [idle]
    try:
        sizes["main-window"] = _grab(window, app, out_dir / f"main-window{suffix}.png")
        if "main-window-idle" in names:
            sizes["main-window-idle"] = _grab(idle, app, out_dir / f"main-window-idle{suffix}.png")
        if "settings" in names:
            dialog = idle.open_settings("Radio")
            dialog.resize(720, 460)
            sizes["settings"] = _grab(dialog, app, out_dir / f"settings{suffix}.png")
        if "close-prompt" in names:
            box, *_ = build_close_box(window)
            widgets.append(box)
            sizes["close-prompt"] = _grab(box, app, out_dir / f"close-prompt{suffix}.png")
        if "ftdi-error" in names:
            error = window.show_error(FTDI_ERROR)
            widgets.append(error)
            sizes["ftdi-error"] = _grab(error, app, out_dir / f"ftdi-error{suffix}.png")
    finally:
        # Destroy everything now: leftover widgets crash a later setStyleSheet().
        for widget in widgets:
            if isinstance(widget, MainWindow):
                widget.quit_app()
            widget.close()
            widget.deleteLater()
        window.quit_app()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    return sizes


def dark_supported(app: QApplication) -> bool:
    """True if this platform switches to a dark scheme on request (offscreen does not)."""
    hints = app.styleHints()
    if not hasattr(hints, "setColorScheme"):  # pragma: no cover - Qt < 6.8
        return False
    hints.setColorScheme(Qt.ColorScheme.Dark)
    app.processEvents()
    dark = hints.colorScheme() == Qt.ColorScheme.Dark
    hints.unsetColorScheme()
    app.processEvents()
    return dark


def capture(
    out_dir: Path,
    app: QApplication,
    *,
    dark: Callable[[QApplication], bool] = dark_supported,
    source: ShotSource | None = None,
) -> list[Path]:
    """Save the scenes in light and dark; return the PNG paths.

    With the emulator (default) every scene is captured. With a real-radio
    ``source`` only the streaming main window is captured (the dialogs show no
    radio data). Dark uses the platform's dark scheme where it honours one,
    otherwise a built-in dark palette (offscreen CI ignores colour-scheme
    requests).
    """
    source = source or emulator_source()
    scenes = SCENES if source.simulated else tuple(s for s in SCENES if s.streaming)
    names = tuple(s.name for s in scenes)
    out_dir.mkdir(parents=True, exist_ok=True)
    original = app.palette()
    light = _capture_theme(app, out_dir, "", source, names)
    native = dark(app)
    try:
        if native:  # pragma: no cover - needs a platform with a real colour scheme
            app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
        else:
            app.setPalette(dark_palette())
        refresh_stylesheet(app)
        dark_sizes = _capture_theme(app, out_dir, "-dark", source, names)
    finally:
        if native:  # pragma: no cover
            app.styleHints().unsetColorScheme()
        else:
            app.setPalette(original)
        refresh_stylesheet(app)
    (out_dir / "screenshot-settings.json").unlink(missing_ok=True)
    manifest = {scene.name: _entry(scene, source, light, dark_sizes) for scene in scenes}
    (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return sorted(out_dir.glob("*.png"))


def _entry(
    scene: Scene,
    source: ShotSource,
    light: dict[str, tuple[int, int]],
    dark_sizes: dict[str, tuple[int, int]],
) -> dict[str, object]:
    alt, caption = scene.alt, scene.caption
    flags: dict[str, object] = {}
    if scene.streaming:
        alt = f"{streaming_alt(source.status)} {source.note}"
        caption = f"{caption} {source.note}"
        flags = {"simulated": True} if source.simulated else {"real_radio": True}
    return {
        "file": f"{scene.name}.png",
        "width": light[scene.name][0],
        "height": light[scene.name][1],
        "alt": alt,
        "caption": caption,
        **flags,
        **({"dark": f"{scene.name}-dark.png"} if scene.name in dark_sizes else {}),
    }
