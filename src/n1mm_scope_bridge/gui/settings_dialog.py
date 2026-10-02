# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""The Settings dialog: a sidebar of pages instead of one long form.

The dialog only holds the controls. ``MainWindow`` reads and writes them,
validates inline, and saves automatically, as before. While streaming, the
pages that affect the stream are read-only (they apply on the next Start).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from n1mm_scope_bridge.radios import RADIOS

SMOOTHING_LABELS = (("latest", "Off"), ("average", "Average"), ("peak", "Peak hold"))
ON_CLOSE_LABELS = (("ask", "Ask me"), ("tray", "Keep running in tray"), ("exit", "Exit"))
RATE_STEPS_PER_HZ = 2  # the slider moves in 0.5 updates per second
PAGES = ("Radio", "N1MM+", "Display", "Startup and closing", "Remote control", "Advanced")
STREAM_PAGES = ("Radio", "N1MM+", "Display", "Advanced")  # read-only while streaming
LOCKED_NOTE = (
    "Streaming now. Stop streaming to change these settings; they apply on the next Start."
)


class Page(QWidget):
    def __init__(self, title: str, hint: str) -> None:
        super().__init__()
        self.setObjectName(f"page:{title}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        note = QLabel(hint)
        note.setObjectName("pageHint")
        note.setWordWrap(True)
        self.locked = QLabel(LOCKED_NOTE)
        self.locked.setObjectName("banner")
        self.locked.setProperty("kind", "warning")
        self.locked.setWordWrap(True)
        self.locked.hide()
        self.form = QFormLayout()
        self.form.setVerticalSpacing(8)
        self.fields = QWidget()
        self.fields.setLayout(self.form)
        layout.addWidget(heading)
        layout.addWidget(note)
        layout.addWidget(self.locked)
        layout.addWidget(self.fields)
        layout.addStretch(1)

    def set_locked(self, locked: bool) -> None:
        self.locked.setVisible(locked)
        self.fields.setEnabled(not locked)


class SettingsDialog(QDialog):
    def __init__(self, browse: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(640, 420)
        self.errors: dict[str, QLabel] = {}
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(184)
        self.sidebar.setSpacing(2)
        self.stack = QStackedWidget()
        self.pages: dict[str, Page] = {}
        builders = (
            (self._radio_page, "Which radio to read, and where FTDI's library is."),
            (self._n1mm_page, "Where N1MM Logger+ is and the name it lists the source under."),
            (self._display_page, "How often N1MM+ is updated and how frames are combined."),
            (self._startup_page, "What happens when the program opens and closes."),
            (
                self._remote_page,
                "Let scripts, N1MM+ {EXEC} macros, or a Stream Deck control the bridge over"
                " UDP. Off by default; it listens only on this PC unless you enter one of this"
                " PC's addresses and an allow-list.",
            ),
            (self._advanced_page, "Rarely needed. Leave these alone unless asked."),
        )
        for name, (build, hint) in zip(PAGES, builders, strict=True):
            page = Page(name, hint)
            build(page.form, browse)
            self.pages[name] = page
            self.stack.addWidget(page)
            self.sidebar.addItem(name)
            self.sidebar.item(self.sidebar.count() - 1).setSizeHint(QSize(0, 36))
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(0)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self.sidebar)
        body.addWidget(self.stack, 1)
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 16, 16, 16)
        column.addLayout(body, 1)
        saved = QLabel("Changes are saved automatically.")
        saved.setObjectName("pageHint")
        footer = QHBoxLayout()
        footer.addWidget(saved)
        footer.addStretch(1)
        footer.addWidget(buttons)
        column.addLayout(footer)

    def show_page(self, name: str) -> None:
        self.sidebar.setCurrentRow(PAGES.index(name))

    def set_streaming(self, streaming: bool) -> None:
        for name in STREAM_PAGES:
            self.pages[name].set_locked(streaming)

    # -- pages ---------------------------------------------------------------------

    def _row(self, form: QFormLayout, label: str, field: object, key: str) -> None:
        form.addRow(label, field)  # type: ignore[call-overload]
        error = QLabel()
        error.setObjectName("fieldError")
        error.setWordWrap(True)
        error.hide()
        form.addRow("", error)
        self.errors[key] = error

    def _radio_page(self, form: QFormLayout, browse: Callable[[], None]) -> None:
        self.radio = QComboBox()
        for key, profile in sorted(RADIOS.items()):
            self.radio.addItem(f"Yaesu {profile.model}", key)
        self.emulator = QCheckBox("Use the built-in emulator (no radio needed)")
        self.emulator.setToolTip("Stream a simulated FT-710 to try the bridge or set up N1MM+")
        self.ftdi_dir = QLineEdit()
        self.ftdi_dir.setPlaceholderText("Search the system path")
        self.browse = QToolButton()
        self.browse.setText("Browse…")
        self.browse.setAccessibleName("Browse for the FTDI library folder")
        self.browse.clicked.connect(browse)
        row = QHBoxLayout()
        row.addWidget(self.ftdi_dir, 1)
        row.addWidget(self.browse)
        self._row(form, "Radio", self.radio, "radio")
        form.addRow("", self.emulator)
        self._row(form, "FTDI library folder", row, "ftdi_lib_dir")

    def _n1mm_page(self, form: QFormLayout, _browse: Callable[[], None]) -> None:
        self.source_name = QLineEdit()
        self.source_name.setToolTip("The name you pick in N1MM+'s Spectrum Display settings")
        self.host = QLineEdit()
        self.host.setToolTip("127.0.0.1 when N1MM+ runs on this PC")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setToolTip("N1MM+ listens for spectrum data on 13064")
        self._row(form, "Source name", self.source_name, "source_name")
        self._row(form, "N1MM+ PC", self.host, "n1mm_host")
        self._row(form, "Port", self.port, "n1mm_port")

    def _display_page(self, form: QFormLayout, _browse: Callable[[], None]) -> None:
        self.rate = QSlider(Qt.Orientation.Horizontal)
        self.rate.setRange(1, 10 * RATE_STEPS_PER_HZ)
        self.rate.setPageStep(RATE_STEPS_PER_HZ)
        self.rate.setAccessibleName("Updates per second")
        self.rate_label = QLabel()
        self.rate_label.setMinimumWidth(112)
        self.rate.valueChanged.connect(
            lambda v: self.rate_label.setText(f"{v / RATE_STEPS_PER_HZ:.1f} per second")
        )
        rate_row = QHBoxLayout()
        rate_row.addWidget(self.rate, 1)
        rate_row.addWidget(self.rate_label)
        self.combine = QComboBox()
        for value, label in SMOOTHING_LABELS:
            self.combine.addItem(label, value)
        self.combine.setToolTip(
            "Off sends each frame as is; Average smooths noise; Peak hold keeps short signals"
        )
        self._row(form, "Updates", rate_row, "rate_hz")
        self._row(form, "Smoothing", self.combine, "combine")

    def _startup_page(self, form: QFormLayout, _browse: Callable[[], None]) -> None:
        self.autostart = QCheckBox("Start streaming when the program opens")
        self.start_hidden = QCheckBox("Start hidden in the system tray")
        self.on_close = QComboBox()
        for value, label in ON_CLOSE_LABELS:
            self.on_close.addItem(label, value)
        self.on_close.setToolTip("What the window's Close button does")
        form.addRow("", self.autostart)
        form.addRow("", self.start_hidden)
        self._row(form, "Close button", self.on_close, "on_close")

    def _remote_page(self, form: QFormLayout, _browse: Callable[[], None]) -> None:
        self.control_enabled = QCheckBox("Enable remote control (UDP)")
        self.control_port = QSpinBox()
        self.control_port.setRange(1, 65535)
        self.control_port.setToolTip("UDP port for commands (default 13070)")
        self.control_bind = QLineEdit()
        self.control_bind.setToolTip(
            "127.0.0.1 = this PC only. For the LAN, one of this PC's own addresses"
            " (never 0.0.0.0), plus an allow-list."
        )
        self.control_allow = QLineEdit()
        self.control_allow.setPlaceholderText("Only needed for the LAN, e.g. 192.168.1.20")
        self.control_allow.setToolTip("Comma-separated IP addresses allowed to send commands")
        self.remote_status = QLabel("Off")
        self.remote_status.setObjectName("pageHint")
        self.remote_status.setWordWrap(True)
        self.remote_status.setAccessibleName("Remote control status")
        form.addRow("", self.control_enabled)
        self._row(form, "Port", self.control_port, "control_port")
        self._row(form, "Listen on", self.control_bind, "control_bind")
        self._row(form, "Allowed clients", self.control_allow, "control_allow")
        form.addRow("Status", self.remote_status)

    def _advanced_page(self, form: QFormLayout, _browse: Callable[[], None]) -> None:
        self.scaling = QDoubleSpinBox()
        self.scaling.setRange(0.01, 10.0)
        self.scaling.setDecimals(4)
        self.scaling.setSingleStep(0.05)
        self.scaling.setSuffix(" dB per step")
        self.scaling.setToolTip("How N1MM+ converts the radio's levels to dB")
        self.device = QLineEdit()
        self.device.setToolTip("The FT4222 device description (normally FT4222 A)")
        self._row(form, "Scaling", self.scaling, "scaling")
        self._row(form, "FT4222 device", self.device, "device")
