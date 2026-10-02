# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Website screenshots of the real GUI in a fixed demo state (#68, part of #22).

``capture(out_dir)`` builds the actual window and dialogs, fills them with
deterministic demo data (FT-710 emulator status, fixed log timestamps), and
saves PNGs with ``QWidget.grab()`` plus a ``manifest.json`` (file names, pixel
sizes, alt text) that ``scripts/build_site.py`` reads. Works offscreen.
"""

from __future__ import annotations

import json
from collections.abc import Callable
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
from n1mm_scope_bridge.transport.ft4222 import Ft4222Reader

WINDOW_SIZE = DEFAULT_SIZE
WATERFALL_FRAMES = HISTORY_ROWS  # demo history fills the waterfall
DEMO_TIME = 1_790_000_000.0  # fixed log timestamps
DEMO_STATUS = ScopeStatus(14_074_000, 20_000, "center", "Center (Normal)")
DEMO_STATS = PipelineStats(frames_read=4_120, frames_dropped=0, bad_frames=0, emitted=824)
FTDI_ERROR = (
    "Could not load FTDI's LibFT4222/D2XX libraries. "
    "Install them from FTDI, or set the FTDI library folder."
)
MANIFEST = "manifest.json"


# Streaming screenshots show the built-in FT-710 emulator, not a real radio, and
# say so in their alt text and caption. Change this (and ``simulated``) once
# screenshots are taken from a real radio (after #111).
SIMULATED_NOTE = "Simulated signals from the built-in FT-710 emulator, not a real radio."


@dataclass(frozen=True)
class Scene:
    name: str
    alt: str
    caption: str
    simulated: bool = False
    """True when the image shows emulator spectrum data (labelled as such)."""

    @property
    def full_alt(self) -> str:
        return f"{self.alt} {SIMULATED_NOTE}" if self.simulated else self.alt

    @property
    def full_caption(self) -> str:
        return f"{self.caption} {SIMULATED_NOTE}" if self.simulated else self.caption


SCENES = (
    Scene(
        "main-window",
        "The N1MM Scope Bridge window streaming a Yaesu FT-710 on 14.074 MHz to N1MM+: "
        "a live spectrum and waterfall of the FT8 segment, cards for frequency, span, "
        "scope mode, N1MM+ rate and health, and the Start/Stop button.",
        "Streaming: the preview shows exactly what N1MM+ receives.",
        simulated=True,
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


def demo_window(settings_path: Path, *, streaming: bool = True) -> MainWindow:
    """The real main window in a fixed state, without starting a stream."""
    window = MainWindow(
        Settings(emulator=True),
        settings_path=settings_path,
        save=lambda _s, _p: None,
        open_url=lambda _u: None,
        tray_available=lambda: False,
        ask=lambda: ("cancel", False),
    )
    window.log = LogBuffer(now=lambda: DEMO_TIME)
    window.log_view.clear()
    if streaming:
        window.model.started()
        window.model.status = DEMO_STATUS
        window.model.stats = DEMO_STATS
        window.model.rate_per_s = 4.0
        for frame in demo_frames():
            window.spectrum.set_frame(frame.spectrum, window.settings.scaling)
        window._set_state("streaming", window._streaming_message())
        window._log("info", "Started streaming FT-710 (emulator) to N1MM+ at 127.0.0.1:13064")
        window._log("info", "Scope: 14.074000 MHz, span 20 kHz, Center (Normal)")
    window.resize(*WINDOW_SIZE)
    return window


def _grab(widget: QWidget, app: QApplication, path: Path) -> tuple[int, int]:
    widget.show()
    app.processEvents()
    pixmap = widget.grab()
    if pixmap.isNull() or not pixmap.save(str(path), "PNG"):
        raise OSError(f"could not save screenshot {path}")
    return pixmap.width(), pixmap.height()


def _capture_theme(app: QApplication, out_dir: Path, suffix: str) -> dict[str, tuple[int, int]]:
    sizes: dict[str, tuple[int, int]] = {}
    window = demo_window(out_dir / "screenshot-settings.json")
    idle = demo_window(out_dir / "screenshot-settings.json", streaming=False)
    widgets: list[QWidget] = [idle]
    try:
        sizes["main-window"] = _grab(window, app, out_dir / f"main-window{suffix}.png")
        sizes["main-window-idle"] = _grab(idle, app, out_dir / f"main-window-idle{suffix}.png")
        dialog = idle.open_settings("Radio")
        dialog.resize(720, 460)
        sizes["settings"] = _grab(dialog, app, out_dir / f"settings{suffix}.png")
        box, *_ = build_close_box(window)
        widgets.append(box)
        sizes["close-prompt"] = _grab(box, app, out_dir / f"close-prompt{suffix}.png")
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
) -> list[Path]:
    """Save every scene in light and dark; return the PNG paths.

    Dark uses the platform's dark scheme where it honours one, otherwise a
    built-in dark palette (offscreen CI ignores colour-scheme requests).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    original = app.palette()
    light = _capture_theme(app, out_dir, "")
    native = dark(app)
    try:
        if native:  # pragma: no cover - needs a platform with a real colour scheme
            app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
        else:
            app.setPalette(dark_palette())
        refresh_stylesheet(app)
        dark_sizes = _capture_theme(app, out_dir, "-dark")
    finally:
        if native:  # pragma: no cover
            app.styleHints().unsetColorScheme()
        else:
            app.setPalette(original)
        refresh_stylesheet(app)
    (out_dir / "screenshot-settings.json").unlink(missing_ok=True)
    manifest = {
        scene.name: {
            "file": f"{scene.name}.png",
            "width": light[scene.name][0],
            "height": light[scene.name][1],
            "alt": scene.full_alt,
            "caption": scene.full_caption,
            **({"simulated": True} if scene.simulated else {}),
            **({"dark": f"{scene.name}-dark.png"} if scene.name in dark_sizes else {}),
        }
        for scene in SCENES
    }
    (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return sorted(out_dir.glob("*.png"))
