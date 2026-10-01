# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Main window: settings form, Start/Stop, and a one-line status.

Settings save automatically. The pipeline runs in ``StreamController``; this
module only touches widgets on the GUI thread.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from n1mm_scope_bridge import settings as settings_mod
from n1mm_scope_bridge.emulator import make_emulator
from n1mm_scope_bridge.gui.controller import Source, StreamController, radio_source
from n1mm_scope_bridge.gui.icon import app_icon
from n1mm_scope_bridge.gui.tray import Asker, TrayController, ask_close, decide_close
from n1mm_scope_bridge.pipeline import PipelineStats
from n1mm_scope_bridge.radios import RADIOS
from n1mm_scope_bridge.radios.base import ScopeStatus
from n1mm_scope_bridge.settings import Settings
from n1mm_scope_bridge.transport.ft4222 import FTDI_DOWNLOAD_URL, Ft4222Reader

APP_TITLE = "N1MM Scope Bridge"
SETUP_GUIDE_URL = "https://github.com/Reid-n0rc/n1mm-scope-bridge/blob/dev/docs/n1mm-setup.md"
SAVE_DELAY_MS = 400
COMBINE_LABELS = (("latest", "Latest"), ("average", "Average (smoother)"), ("peak", "Peak hold"))
ON_CLOSE_LABELS = (("ask", "Ask me"), ("tray", "Keep running in tray"), ("exit", "Exit"))
EMULATOR_FPS = 20.0


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


def stats_text(stats: PipelineStats) -> str:
    return f"Sent {stats.emitted} · dropped {stats.frames_dropped} · bad {stats.bad_frames}"


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
        self.setMinimumWidth(480)
        self._settings = settings
        self._settings_path = settings_path
        self._save = save
        self._open_url = open_url
        self.controller = controller or StreamController(source_factory=gui_source, parent=self)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_settings)
        self._errors: dict[str, QLabel] = {}
        self._build()
        self._load(settings)
        self.controller.started.connect(self._on_started)
        self.controller.stopped.connect(self._on_stopped)
        self.controller.status.connect(self._on_status)
        self.controller.stats.connect(self._on_stats)
        self.tray: TrayController | None = None
        if tray_available():
            self.tray = TrayController(self.windowIcon(), self)
            self.tray.show_requested.connect(self.show_window)
            self.tray.toggle_requested.connect(self._toggle_from_tray)
            self.tray.exit_requested.connect(self.quit_app)
            self.tray.show()
        self._set_state("stopped")

    # -- layout ----------------------------------------------------------------

    def _build(self) -> None:
        root = QWidget(self)
        column = QVBoxLayout(root)
        column.addLayout(self._build_header())
        column.addWidget(self._build_radio_box())
        column.addWidget(self._build_n1mm_box())
        column.addWidget(self._build_behaviour_box())
        self.status = QLabel("Not streaming")
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.counters = QLabel("")
        column.addWidget(self.status)
        column.addWidget(self.counters)
        column.addLayout(self._build_buttons())
        self.setCentralWidget(root)
        self._connect_changes()

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title = QLabel(APP_TITLE)
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 1.4)
        font.setBold(True)
        title.setFont(font)
        self.chip = QLabel()
        self.chip.setObjectName("statusChip")
        self.chip.setAccessibleName("Streaming status")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.chip)
        return header

    def _build_radio_box(self) -> QGroupBox:
        radio_box = QGroupBox("Radio")
        radio_form = QFormLayout(radio_box)
        self.radio = QComboBox()
        for key, profile in sorted(RADIOS.items()):
            self.radio.addItem(profile.model, key)
        self.emulator = QCheckBox("Use the built-in emulator (no radio needed)")
        self.emulator.setToolTip("Stream a simulated FT-710 to try the bridge or set up N1MM+")
        self.ftdi_dir = QLineEdit()
        self.ftdi_dir.setPlaceholderText("Search the system path")
        browse = QToolButton()
        browse.setText("Browse…")
        browse.setAccessibleName("Browse for the FTDI library folder")
        browse.clicked.connect(self._browse_ftdi)
        ftdi_row = QHBoxLayout()
        ftdi_row.addWidget(self.ftdi_dir, 1)
        ftdi_row.addWidget(browse)
        self._row(radio_form, "Radio", self.radio, "radio")
        radio_form.addRow("", self.emulator)
        self._row(radio_form, "FTDI library folder", ftdi_row, "ftdi_lib_dir")
        return radio_box

    def _build_n1mm_box(self) -> QGroupBox:
        n1mm_box = QGroupBox("N1MM Logger+")
        n1mm_form = QFormLayout(n1mm_box)
        self.source_name = QLineEdit()
        self.source_name.setToolTip("The name you pick in N1MM+'s Spectrum Display settings")
        self.host = QLineEdit()
        self.host.setToolTip("127.0.0.1 when N1MM+ runs on this PC")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0.5, 10.0)
        self.rate.setSingleStep(0.5)
        self.rate.setDecimals(1)
        self.rate.setSuffix(" per second")
        self.combine = QComboBox()
        for value, label in COMBINE_LABELS:
            self.combine.addItem(label, value)
        self.scaling = QDoubleSpinBox()
        self.scaling.setRange(0.01, 10.0)
        self.scaling.setDecimals(4)
        self.scaling.setSingleStep(0.05)
        self.scaling.setSuffix(" dB per step")
        self._row(n1mm_form, "Source name", self.source_name, "source_name")
        self._row(n1mm_form, "N1MM+ PC", self.host, "n1mm_host")
        self._row(n1mm_form, "Port", self.port, "n1mm_port")
        self._row(n1mm_form, "Updates", self.rate, "rate_hz")
        self._row(n1mm_form, "Display", self.combine, "combine")
        self._row(n1mm_form, "Scaling", self.scaling, "scaling")
        return n1mm_box

    def _build_behaviour_box(self) -> QGroupBox:
        box = QGroupBox("Startup and closing")
        box.setObjectName("behaviourBox")  # stays editable while streaming
        form = QFormLayout(box)
        self.autostart = QCheckBox("Start streaming when the program opens")
        self.start_hidden = QCheckBox("Start hidden in the system tray")
        self.on_close = QComboBox()
        for value, label in ON_CLOSE_LABELS:
            self.on_close.addItem(label, value)
        self.on_close.setToolTip("What the window's Close button does")
        form.addRow("", self.autostart)
        form.addRow("", self.start_hidden)
        self._row(form, "Close button", self.on_close, "on_close")
        return box

    def _build_buttons(self) -> QHBoxLayout:
        buttons = QHBoxLayout()
        guide = QPushButton("N1MM+ setup guide")
        guide.setFlat(True)
        guide.clicked.connect(lambda: self._open_url(QUrl(SETUP_GUIDE_URL)))
        self.start_stop = QPushButton("Start")
        self.start_stop.setObjectName("primary")
        self.start_stop.setDefault(True)
        self.start_stop.clicked.connect(self.toggle_streaming)
        buttons.addWidget(guide)
        buttons.addStretch(1)
        buttons.addWidget(self.start_stop)
        return buttons

    def _connect_changes(self) -> None:
        for widget in (self.source_name, self.host, self.ftdi_dir):
            widget.textChanged.connect(self._changed)
        for spin in (self.port, self.rate, self.scaling):
            spin.valueChanged.connect(self._changed)
        for combo in (self.radio, self.combine, self.on_close):
            combo.currentIndexChanged.connect(self._changed)
        for check in (self.emulator, self.autostart, self.start_hidden):
            check.toggled.connect(self._changed)

    def _row(self, form: QFormLayout, label: str, field: object, key: str) -> None:
        form.addRow(label, field)  # type: ignore[call-overload]
        error = QLabel()
        error.setObjectName("fieldError")
        error.setWordWrap(True)
        error.hide()
        form.addRow("", error)
        self._errors[key] = error

    # -- settings <-> form -------------------------------------------------------

    def _load(self, s: Settings) -> None:
        index = self.radio.findData(s.radio)
        self.radio.setCurrentIndex(max(index, 0))
        self.emulator.setChecked(s.emulator)
        self.ftdi_dir.setText(s.ftdi_lib_dir)
        self.source_name.setText(s.source_name)
        self.source_name.setPlaceholderText(s.effective_name())
        self.host.setText(s.n1mm_host)
        self.port.setValue(s.n1mm_port)
        self.rate.setValue(s.rate_hz)
        self.combine.setCurrentIndex(max(self.combine.findData(s.combine), 0))
        self.scaling.setValue(s.scaling)
        self.autostart.setChecked(s.start_streaming_on_launch)
        self.start_hidden.setChecked(s.start_minimized)
        self.on_close.setCurrentIndex(max(self.on_close.findData(s.on_close), 0))

    def form_settings(self) -> Settings:
        return self._settings.replace(
            radio=self.radio.currentData(),
            emulator=self.emulator.isChecked(),
            ftdi_lib_dir=self.ftdi_dir.text().strip(),
            source_name=self.source_name.text(),
            n1mm_host=self.host.text().strip(),
            n1mm_port=self.port.value(),
            rate_hz=self.rate.value(),
            combine=self.combine.currentData(),
            scaling=self.scaling.value(),
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
            return
        self.save_settings()
        self.controller.start(self._settings)

    def _set_state(self, state: str, message: str = "") -> None:
        labels = {"stopped": "Stopped", "streaming": "Streaming", "error": "Error"}
        self.chip.setText(labels[state])
        self.chip.setProperty("state", state)
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)
        running = state == "streaming"
        self.start_stop.setText("Stop" if running else "Start")
        for box in self.findChildren(QGroupBox):
            if box.objectName() != "behaviourBox":
                box.setEnabled(not running)
        if message:
            self.status.setText(message)
        if self.tray is not None:
            self.tray.set_status(labels[state], streaming=running)

    def _on_started(self) -> None:
        target = f"{self._settings.n1mm_host}:{self._settings.n1mm_port}"
        self._set_state(
            "streaming", f"Streaming to N1MM+ at {target} as {self._settings.effective_name()!r}"
        )

    def _on_stopped(self, error: str) -> None:
        if not error:
            self._set_state("stopped", "Not streaming")
            return
        self._set_state("error", error)
        self.show_error(error)

    def _on_status(self, status: ScopeStatus) -> None:
        text = status_text(status)
        if not status.edges_verified:
            text += " — set the radio's scope to Center mode for exact frequencies"
        self.status.setText(text)

    def _on_stats(self, stats: PipelineStats) -> None:
        self.counters.setText(stats_text(stats))

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

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.tray is not None
        ):
            QTimer.singleShot(0, self.hide_to_tray)
