# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""GUI entry point (``n1mm-scope-bridge-gui``) and the ``--self-test`` smoke test."""

from __future__ import annotations

import argparse
import socket
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import QApplication

from n1mm_scope_bridge import __version__
from n1mm_scope_bridge import settings as settings_mod
from n1mm_scope_bridge.gui.main_window import APP_TITLE, MainWindow
from n1mm_scope_bridge.gui.style import apply_style

SELF_TEST_TIMEOUT_S = 15.0
SELF_TEST_PACKETS = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="n1mm-scope-bridge-gui", description=APP_TITLE)
    parser.add_argument("--settings", type=Path, help="settings file (default: per-user file)")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="open the window, stream the emulator to a local listener, and exit 0 on success",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def application(argv: Sequence[str] | None = None) -> QApplication:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication(list(argv or [sys.argv[0]]))
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("n1mm-scope-bridge")
    app.setProperty("bridgeStyle", apply_style(app))
    return app


def self_test(app: QApplication, settings_path: Path) -> tuple[bool, str]:
    """Stream the emulator through the real window to a loopback UDP listener."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        rx.setblocking(False)
        settings = settings_mod.Settings(
            emulator=True, n1mm_host="127.0.0.1", n1mm_port=rx.getsockname()[1], rate_hz=10.0
        )
        window = MainWindow(settings, settings_path=settings_path)
        window.show()
        window.toggle_streaming()
        packets = 0
        deadline = time.monotonic() + SELF_TEST_TIMEOUT_S
        while time.monotonic() < deadline and packets < SELF_TEST_PACKETS:
            app.processEvents()
            try:
                if b"<Spectrum>" in rx.recv(65535):
                    packets += 1
            except BlockingIOError:
                time.sleep(0.02)
        status_ok = window.status.text().startswith(("VFO", "Streaming"))
        # quit_app, not close(): with a system tray, close() would open the
        # "keep running in the tray?" prompt and block the unattended test.
        window.quit_app()
        app.processEvents()
    if packets < SELF_TEST_PACKETS:
        return False, f"self-test: received {packets} N1MM packets, expected {SELF_TEST_PACKETS}"
    if not status_ok:
        return False, f"self-test: status line not updated ({window.status.text()!r})"
    return True, f"self-test: OK ({packets} packets, style {app.property('bridgeStyle')})"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = application()
    if args.self_test:
        path = args.settings or Path(settings_mod.settings_path().parent / "self-test.json")
        ok, message = self_test(app, path)
        print(message, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    path = args.settings or settings_mod.settings_path()
    settings, warnings = settings_mod.load(path)
    window = MainWindow(settings, settings_path=path)
    # With a tray icon, hiding the window must not quit the program.
    app.setQuitOnLastWindowClosed(window.tray is None)
    if settings.start_minimized and window.tray is not None:
        window.hide_to_tray()
    else:
        window.show()
    if warnings:
        window.show_error("\n".join(warnings))
    if settings.start_streaming_on_launch:
        window.toggle_streaming()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
