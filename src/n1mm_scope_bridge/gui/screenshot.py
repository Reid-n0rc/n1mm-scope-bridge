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

from n1mm_scope_bridge.gui.main_window import MainWindow, status_text
from n1mm_scope_bridge.gui.status import LogBuffer
from n1mm_scope_bridge.gui.tray import build_close_box
from n1mm_scope_bridge.pipeline import PipelineStats
from n1mm_scope_bridge.radios.base import ScopeStatus
from n1mm_scope_bridge.settings import Settings

WINDOW_SIZE = (720, 960)
DEMO_TIME = 1_790_000_000.0  # fixed log timestamps
DEMO_STATUS = ScopeStatus(14_074_000, 20_000, "center", "Center (Normal)")
DEMO_STATS = PipelineStats(frames_read=4_120, frames_dropped=0, bad_frames=0, emitted=824)
FTDI_ERROR = (
    "Could not load FTDI's LibFT4222/D2XX libraries. "
    "Install them from FTDI, or set the FTDI library folder."
)
MANIFEST = "manifest.json"


@dataclass(frozen=True)
class Scene:
    name: str
    alt: str
    caption: str


SCENES = (
    Scene(
        "main-window",
        "The N1MM Scope Bridge window streaming a Yaesu FT-710 on 14.074 MHz to N1MM+, "
        "with the radio and N1MM+ settings, a live status panel, and the log.",
        "The main window while streaming: settings, live status, and the log.",
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


def demo_window(settings_path: Path) -> MainWindow:
    """The real main window in a fixed streaming state, without starting a stream."""
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
    window.model.started()
    window.model.status = DEMO_STATUS
    window.model.stats = DEMO_STATS
    window.model.rate_per_s = 4.0
    window._set_state("streaming", status_text(DEMO_STATUS))
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
    widgets: list[QWidget] = []
    try:
        sizes["main-window"] = _grab(window, app, out_dir / f"main-window{suffix}.png")
        box, *_ = build_close_box(window)
        widgets.append(box)
        sizes["close-prompt"] = _grab(box, app, out_dir / f"close-prompt{suffix}.png")
        error = window.show_error(FTDI_ERROR)
        widgets.append(error)
        sizes["ftdi-error"] = _grab(error, app, out_dir / f"ftdi-error{suffix}.png")
    finally:
        # Destroy everything now: leftover widgets crash a later setStyleSheet().
        for widget in widgets:
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
    """Save every scene (and dark variants where supported); return the PNG paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    light = _capture_theme(app, out_dir, "")
    dark_sizes: dict[str, tuple[int, int]] = {}
    if dark(app):  # pragma: no cover - needs a platform with a real colour scheme
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
        try:
            dark_sizes = _capture_theme(app, out_dir, "-dark")
        finally:
            app.styleHints().unsetColorScheme()
    (out_dir / "screenshot-settings.json").unlink(missing_ok=True)
    manifest = {
        scene.name: {
            "file": f"{scene.name}.png",
            "width": light[scene.name][0],
            "height": light[scene.name][1],
            "alt": scene.alt,
            "caption": scene.caption,
            **({"dark": f"{scene.name}-dark.png"} if scene.name in dark_sizes else {}),
        }
        for scene in SCENES
    }
    (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return sorted(out_dir.glob("*.png"))
