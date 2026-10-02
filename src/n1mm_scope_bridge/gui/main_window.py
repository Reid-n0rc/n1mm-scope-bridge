# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Main window: a dashboard of what is being sent to N1MM+.

Layout (top to bottom): a header (title, status pill, Start/Stop, menu), the
live spectrum and waterfall preview, a row of cards (frequency, span, scope
mode, N1MM+, health), a one-line message, and a collapsible Activity log.
Settings live in ``SettingsDialog`` and save automatically. The pipeline runs
in ``StreamController``; this module only touches widgets on the GUI thread.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from n1mm_scope_bridge import settings as settings_mod
from n1mm_scope_bridge.emulator import make_emulator
from n1mm_scope_bridge.gui import icons
from n1mm_scope_bridge.gui.controller import Source, StreamController, radio_source
from n1mm_scope_bridge.gui.icon import app_icon
from n1mm_scope_bridge.gui.settings_dialog import RATE_STEPS_PER_HZ, SettingsDialog
from n1mm_scope_bridge.gui.spectrum import SpectrumView
from n1mm_scope_bridge.gui.status import LOG_LINES, LogBuffer, StatusModel, diagnostics
from n1mm_scope_bridge.gui.style import Theme
from n1mm_scope_bridge.gui.tray import Asker, TrayController, ask_close, decide_close
from n1mm_scope_bridge.gui.widgets import Badge, Card
from n1mm_scope_bridge.pipeline import PipelineStats
from n1mm_scope_bridge.radios import get_radio
from n1mm_scope_bridge.radios.base import ParsedFrame, ScopeStatus
from n1mm_scope_bridge.settings import Settings
from n1mm_scope_bridge.transport.ft4222 import FTDI_DOWNLOAD_URL, Ft4222Reader

APP_TITLE = "N1MM Scope Bridge"
SETUP_GUIDE_URL = "https://reid-n0rc.github.io/n1mm-scope-bridge/n1mm.html"
SAVE_DELAY_MS = 400
EMULATOR_FPS = 20.0
DEFAULT_SIZE = (960, 640)
MINIMUM_SIZE = (760, 540)
STATES = {
    "stopped": ("Stopped", "neutral"),
    "streaming": ("Streaming", "success"),
    "error": ("Error", "danger"),
}


def quit_application() -> None:
    """End the Qt event loop (a seam so tests don't patch Qt classes)."""
    QApplication.quit()


def gui_source(settings: Settings) -> Source:
    """The radio, or the built-in emulator when the ``emulator`` setting is on."""
    if settings.emulator:
        reader = Ft4222Reader(make_emulator("steady", fps=EMULATOR_FPS))
        return reader, reader.stop
    return radio_source(settings)


def status_text(status: ScopeStatus) -> str:
    return (
        f"VFO {status.vfo_hz / 1e6:.6f} MHz · span {status.span_hz / 1e3:g} kHz · "
        f"{status.mode_name}"
    )


def frequency_text(hz: int) -> str:
    """``14.074 000 MHz``: MHz with the last three digits grouped, like a radio display."""
    mhz, rest = divmod(hz, 1_000_000)
    return f"{mhz}.{rest // 1000:03d} {rest % 1000:03d} MHz"


def short_mode(name: str) -> str:
    """``Center (Normal)`` -> ``Center``."""
    return name.split(" (", maxsplit=1)[0]


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Settings,
        *,
        settings_path: Path | None = None,
        controller: StreamController | None = None,
        save: Callable[[Settings, Path | None], object] = settings_mod.save,
        open_url: Callable[[QUrl], object] = QDesktopServices.openUrl,
        tray_available: Callable[[], bool] = QSystemTrayIcon.isSystemTrayAvailable,
        ask: Asker | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(app_icon(self.palette()))
        self._ask = ask or (lambda: ask_close(self))
        self._quitting = False
        self.setMinimumSize(*MINIMUM_SIZE)
        self.resize(*DEFAULT_SIZE)
        self._settings = settings
        self._settings_path = settings_path
        self._save = save
        self._open_url = open_url
        self.controller = controller or StreamController(source_factory=gui_source, parent=self)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_settings)
        self.model = StatusModel()
        self.log = LogBuffer()
        self._state = "stopped"
        self.settings_dialog = SettingsDialog(self._browse_ftdi, self)
        self._adopt_settings_fields()
        self._build()
        self._load(settings)
        self._connect_changes()
        self.controller.started.connect(self._on_started)
        self.controller.stopped.connect(self._on_stopped)
        self.controller.status.connect(self._on_status)
        self.controller.stats.connect(self._on_stats)
        self.controller.frame.connect(self._on_frame)
        self.controller.warning.connect(lambda message: self._log("warning", message))
        self.tray: TrayController | None = None
        if tray_available():
            self.tray = TrayController(self.windowIcon(), self)
            self.tray.show_requested.connect(self.show_window)
            self.tray.toggle_requested.connect(self._toggle_from_tray)
            self.tray.exit_requested.connect(self.quit_app)
            self.tray.show()
        self._set_state("stopped")

    # -- layout ----------------------------------------------------------------

    def _adopt_settings_fields(self) -> None:
        """Expose the dialog's controls on the window (the form API callers use)."""
        d = self.settings_dialog
        self.radio, self.emulator, self.ftdi_dir = d.radio, d.emulator, d.ftdi_dir
        self.source_name, self.host, self.port = d.source_name, d.host, d.port
        self.rate, self.combine, self.scaling = d.rate, d.combine, d.scaling
        self.autostart, self.start_hidden, self.on_close = d.autostart, d.start_hidden, d.on_close
        self.device = d.device
        self._errors = d.errors

    def _build(self) -> None:
        root = QWidget(self)
        root.setObjectName("root")
        column = QVBoxLayout(root)
        column.setContentsMargins(16, 12, 16, 12)
        column.setSpacing(12)
        column.addLayout(self._build_header())
        column.addWidget(self._build_hero(), 1)
        column.addLayout(self._build_cards())
        self.status = QLabel("Not streaming")
        self.status.setObjectName("message")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self.status)
        column.addWidget(self._build_activity())
        self.setCentralWidget(root)
        self._apply_icons()

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(12)
        self.logo = QLabel()
        self.logo.setPixmap(self.windowIcon().pixmap(QSize(36, 36)))
        title = QLabel(APP_TITLE)
        title.setObjectName("appTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("subtitle")
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(title)
        names.addWidget(self.subtitle)
        self.chip = Badge(role="pill")
        self.chip.setAccessibleName("Streaming status")
        self.start_stop = QPushButton("Start")
        self.start_stop.setObjectName("primary")
        self.start_stop.setDefault(True)
        self.start_stop.setIconSize(QSize(16, 16))
        self.start_stop.clicked.connect(self.toggle_streaming)
        self.settings_button = QToolButton()
        self.settings_button.setObjectName("flat")
        self.settings_button.setToolTip("Settings")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        self.menu_button = QToolButton()
        self.menu_button.setObjectName("flat")
        self.menu_button.setToolTip("More")
        self.menu_button.setAccessibleName("More actions")
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.menu_button)
        self.action_settings = self._action("Settings…", self.open_settings)
        self.action_diagnostics = self._action("Copy diagnostics", self.copy_diagnostics)
        self.action_guide = self._action(
            "N1MM+ setup guide", lambda: self._open_url(QUrl(SETUP_GUIDE_URL))
        )
        self.action_about = self._action("About and license", self.show_about)
        self.menu_button.setMenu(self.menu)
        header.addWidget(self.logo)
        header.addLayout(names)
        header.addStretch(1)
        header.addWidget(self.chip)
        header.addWidget(self.start_stop)
        header.addWidget(self.settings_button)
        header.addWidget(self.menu_button)
        return header

    def _action(self, text: str, slot: Callable[[], object]) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(lambda _checked=False: slot())
        self.menu.addAction(action)
        return action

    def _build_hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("card")
        layout = QVBoxLayout(hero)
        layout.setContentsMargins(8, 8, 8, 8)
        self.spectrum = SpectrumView()
        layout.addWidget(self.spectrum)
        return hero

    def _build_cards(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.cards = {
            "frequency": Card("Frequency", monospace=True),
            "span": Card("Span"),
            "mode": Card("Scope mode"),
            "n1mm": Card("To N1MM+"),
            "health": Card("Health"),
        }
        for card in self.cards.values():
            row.addWidget(card, 1)
        self.cards["frequency"].setMinimumWidth(200)
        return row

    def _build_activity(self) -> QFrame:
        drawer = QFrame()
        drawer.setObjectName("card")
        layout = QVBoxLayout(drawer)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(6)
        bar = QHBoxLayout()
        self.activity_toggle = QToolButton()
        self.activity_toggle.setObjectName("flat")
        self.activity_toggle.setText("Activity")
        self.activity_toggle.setCheckable(True)
        self.activity_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.activity_toggle.setAccessibleName("Show activity log")
        self.activity_toggle.toggled.connect(self.set_activity_open)
        self.activity_last = QLabel()
        self.activity_last.setObjectName("cardDetail")
        self.copy_button = QPushButton("Copy diagnostics")
        self.copy_button.setToolTip(
            "Copy version, settings, status, and recent log lines for a bug report"
        )
        self.copy_button.clicked.connect(self.copy_diagnostics)
        bar.addWidget(self.activity_toggle)
        bar.addWidget(self.activity_last, 1)
        bar.addWidget(self.copy_button)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(LOG_LINES)
        self.log_view.setAccessibleName("Activity log")
        self.log_view.setFixedHeight(140)
        self.log_view.hide()
        layout.addLayout(bar)
        layout.addWidget(self.log_view)
        return drawer

    def set_activity_open(self, opened: bool) -> None:
        self.log_view.setVisible(opened)
        self.activity_toggle.setChecked(opened)
        self._apply_icons()

    def _apply_icons(self) -> None:
        theme = Theme.from_palette(self.palette())
        running = self._state == "streaming"
        self.start_stop.setIcon(
            icons.icon("square" if running else "play", theme.text if running else theme.on_accent)
        )
        self.settings_button.setIcon(icons.icon("settings", theme.text))
        self.menu_button.setIcon(icons.icon("ellipsis", theme.text))
        self.activity_toggle.setIcon(
            icons.icon("chevron-up" if self.log_view.isVisible() else "chevron-down", theme.text)
        )
        for action, name in (
            (self.action_settings, "settings"),
            (self.action_diagnostics, "copy"),
            (self.action_guide, "book-open"),
            (self.action_about, "info"),
        ):
            action.setIcon(icons.icon(name, theme.text))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._apply_icons()
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.tray is not None
        ):
            QTimer.singleShot(0, self.hide_to_tray)

    # -- status presentation ------------------------------------------------------

    def _refresh_status(self) -> None:
        s, st, model = self.model.status, self.model.stats, self.model
        name = self._settings.effective_name()
        try:
            model_name = get_radio(self._settings.radio).model
        except KeyError:
            model_name = self._settings.radio
        source = "emulator" if self._settings.emulator else "USB"
        self.subtitle.setText(f"Yaesu {model_name} ({source}) → N1MM+ as “{name}”")
        cards = self.cards
        if s is None:
            for key in ("frequency", "span", "mode"):
                cards[key].value.setText("—")
            cards["frequency"].detail.setText("VFO-A")
            cards["span"].detail.setText("")
            cards["mode"].detail.setText("")
            cards["mode"].show_chip("", "neutral")
        else:
            cards["frequency"].value.setText(frequency_text(s.vfo_hz))
            cards["frequency"].detail.setText("VFO-A")
            cards["span"].value.setText(f"{s.span_hz / 1e3:g} kHz")
            low, high = s.vfo_hz - s.span_hz // 2, s.vfo_hz + s.span_hz // 2
            cards["span"].detail.setText(f"{low / 1e6:.3f} to {high / 1e6:.3f} MHz")
            cards["mode"].value.setText(short_mode(s.mode_name))
            cards["mode"].detail.setText(s.mode_name)
            if s.edges_verified:
                cards["mode"].show_chip("✓ Exact frequencies", "success")
            else:
                cards["mode"].show_chip("Switch the radio to Center", "warning")
        target = f"{self._settings.n1mm_host}:{self._settings.n1mm_port}"
        rate = f"{model.rate_per_s:.1f} per second" if model.streaming else "Idle"
        cards["n1mm"].value.setText(rate)
        cards["n1mm"].detail.setText(target)
        cards["n1mm"].setToolTip(f"{st.emitted} updates sent this session" if st else "")
        if model.last_error:
            cards["health"].value.setText("Problem")
            cards["health"].show_chip(model.last_error[:48], "danger")
        elif st and (st.frames_dropped or st.bad_frames):
            cards["health"].value.setText("Degraded")
            cards["health"].show_chip("", "neutral")
        else:
            cards["health"].value.setText("OK" if model.streaming else "—")
            cards["health"].show_chip("", "neutral")
        cards["health"].detail.setText(
            f"{st.frames_dropped} dropped · {st.bad_frames} bad" if st else ""
        )
        if self.tray is not None:
            self.tray.set_status(model.summary(name), streaming=model.streaming)

    @property
    def status_rows(self) -> dict[str, str]:
        """The status panel as label -> text (diagnostics and tests)."""
        return dict(self.model.rows())

    def _log(self, level: str, message: str) -> None:
        line = self.log.add(level, message)
        self.log_view.appendPlainText(line)
        self.activity_last.setText(line)

    def copy_diagnostics(self) -> str:
        text = diagnostics(self._settings, self.model, self.log)
        QApplication.clipboard().setText(text)
        self._log("info", "Diagnostics copied to the clipboard")
        return text

    def show_about(self) -> None:
        from n1mm_scope_bridge.cli import LEGAL_NOTICE  # noqa: PLC0415 - avoid import cycle

        QMessageBox.about(self, f"About {APP_TITLE}", LEGAL_NOTICE.replace("\n", "<br>"))

    # -- settings <-> form -------------------------------------------------------

    def _connect_changes(self) -> None:
        for widget in (self.source_name, self.host, self.ftdi_dir, self.device):
            widget.textChanged.connect(self._changed)
        for spin in (self.port, self.rate, self.scaling):
            spin.valueChanged.connect(self._changed)
        for combo in (self.radio, self.combine, self.on_close):
            combo.currentIndexChanged.connect(self._changed)
        for check in (self.emulator, self.autostart, self.start_hidden):
            check.toggled.connect(self._changed)

    def _load(self, s: Settings) -> None:
        self.radio.setCurrentIndex(max(self.radio.findData(s.radio), 0))
        self.emulator.setChecked(s.emulator)
        self.ftdi_dir.setText(s.ftdi_lib_dir)
        self.source_name.setText(s.source_name)
        self.source_name.setPlaceholderText(s.effective_name())
        self.host.setText(s.n1mm_host)
        self.port.setValue(s.n1mm_port)
        self.rate.setValue(round(s.rate_hz * RATE_STEPS_PER_HZ))
        self.combine.setCurrentIndex(max(self.combine.findData(s.combine), 0))
        self.scaling.setValue(s.scaling)
        self.device.setText(s.device)
        self.autostart.setChecked(s.start_streaming_on_launch)
        self.start_hidden.setChecked(s.start_minimized)
        self.on_close.setCurrentIndex(max(self.on_close.findData(s.on_close), 0))
        self.settings_dialog.rate_label.setText(f"{s.rate_hz:.1f} per second")

    def form_settings(self) -> Settings:
        return self._settings.replace(
            radio=self.radio.currentData(),
            emulator=self.emulator.isChecked(),
            ftdi_lib_dir=self.ftdi_dir.text().strip(),
            source_name=self.source_name.text(),
            n1mm_host=self.host.text().strip(),
            n1mm_port=self.port.value(),
            rate_hz=self.rate.value() / RATE_STEPS_PER_HZ,
            combine=self.combine.currentData(),
            scaling=self.scaling.value(),
            device=self.device.text().strip(),
            start_streaming_on_launch=self.autostart.isChecked(),
            start_minimized=self.start_hidden.isChecked(),
            on_close=self.on_close.currentData(),
        )

    @property
    def settings(self) -> Settings:
        return self._settings

    def _changed(self) -> None:
        self._settings = self.form_settings()
        self.show_problems(self._settings.validate())
        self._refresh_status()
        self._save_timer.start()

    def save_settings(self) -> None:
        self._save_timer.stop()
        try:
            self._save(self._settings, self._settings_path)
        except OSError as err:
            self.status.setText(f"Could not save settings: {err}")

    def show_problems(self, problems: dict[str, str]) -> None:
        for key, label in self._errors.items():
            message = problems.get(key, "")
            label.setText(f"⚠ {message}" if message else "")
            label.setVisible(bool(message))

    def open_settings(self, page: str | None = None) -> SettingsDialog:
        if page:
            self.settings_dialog.show_page(page)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        return self.settings_dialog

    def _browse_ftdi(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "FTDI library folder", self.ftdi_dir.text())
        if folder:
            self.ftdi_dir.setText(folder)

    # -- streaming ----------------------------------------------------------------

    def toggle_streaming(self) -> None:
        if self.controller.running:
            self.controller.stop()
            return
        self._settings = self.form_settings()
        problems = self._settings.validate()
        self.show_problems(problems)
        if problems:
            self._set_state("error", "Fix the highlighted settings, then press Start.")
            first = next(iter(problems))
            page = next(
                (name for name, p in self.settings_dialog.pages.items()
                 if self._errors[first] in p.findChildren(QLabel)),
                None,
            )  # fmt: skip
            self.open_settings(page)
            return
        self.save_settings()
        self.controller.start(self._settings)

    def _set_state(self, state: str, message: str = "") -> None:
        text, kind = STATES[state]
        self._state = state
        self.chip.setText(text)
        self.chip.set_kind(kind)
        running = state == "streaming"
        self.start_stop.setText("Stop" if running else "Start")
        self.start_stop.setProperty("running", running)
        self.start_stop.style().unpolish(self.start_stop)
        self.start_stop.style().polish(self.start_stop)
        self.settings_dialog.set_streaming(running)
        if message:
            self.status.setText(message)
        self._apply_icons()
        self._refresh_status()

    def _streaming_message(self) -> str:
        target = f"{self._settings.n1mm_host}:{self._settings.n1mm_port}"
        return f"Streaming to N1MM+ at {target} as {self._settings.effective_name()!r}"

    def _on_started(self) -> None:
        message = self._streaming_message()
        self.model.started()
        self.spectrum.clear()
        self._log("info", message)
        self._set_state("streaming", message)

    def _on_stopped(self, error: str) -> None:
        self.model.stopped(error)
        if not error:
            self._log("info", "Stopped streaming")
            self._set_state("stopped", "Not streaming")
            return
        self._log("error", error)
        self._set_state("error", error)
        self.show_error(error)

    def _on_status(self, status: ScopeStatus) -> None:
        if status.edges_verified:
            self.status.setText(self._streaming_message())
        else:
            self.status.setText(
                f"The radio's scope is in {status.mode_name} mode. Set it to Center mode for"
                " exact frequencies in N1MM+."
            )
        self.model.status = status
        self._refresh_status()

    def _on_stats(self, stats: PipelineStats) -> None:
        self.model.update_stats(stats)
        self._refresh_status()

    def _on_frame(self, item: ParsedFrame) -> None:
        self.spectrum.set_frame(item.spectrum, self._settings.scaling)

    def show_error(self, message: str) -> QMessageBox:
        box = QMessageBox(QMessageBox.Icon.Warning, APP_TITLE, message, parent=self)
        box.setWindowModality(Qt.WindowModality.WindowModal)
        if "FTDI" in message:
            download = box.addButton("Open FTDI download page", QMessageBox.ButtonRole.HelpRole)
            download.clicked.connect(lambda: self._open_url(QUrl(FTDI_DOWNLOAD_URL)))
        box.addButton(QMessageBox.StandardButton.Ok)
        box.open()
        return box

    # -- tray, close, minimize (#19) -------------------------------------------------

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self) -> None:
        """Hide the window; streaming continues and the tray icon stays."""
        if self.tray is None:
            self.showMinimized()
            return
        self.hide()
        self.tray.show()
        self.tray.hint_once()

    def _toggle_from_tray(self) -> None:
        self.toggle_streaming()
        if self.chip.text() == "Error":
            self.show_window()  # show what needs fixing

    def quit_app(self) -> None:
        """Stop streaming and exit (tray menu Exit, or the Exit choice on close)."""
        self._quitting = True
        self.close()

    def _shutdown(self) -> None:
        self.controller.stop()
        self.save_settings()
        self.settings_dialog.close()
        if self.tray is not None:
            self.tray.icon.hide()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting or self.tray is None:
            self._shutdown()
            event.accept()
            return
        decision = decide_close(self._settings.on_close, True, self._ask)
        if decision.remember is not None:
            self.on_close.setCurrentIndex(self.on_close.findData(decision.remember))
            self.save_settings()
        if decision.action == "tray":
            event.ignore()
            self.hide_to_tray()
        elif decision.action == "exit":
            self._quitting = True
            self._shutdown()
            event.accept()
            quit_application()
        else:
            event.ignore()
