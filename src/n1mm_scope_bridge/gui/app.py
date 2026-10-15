# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""GUI entry point (``n1mm-scope-bridge-gui``) and the ``--self-test`` smoke test."""

from __future__ import annotations

import argparse
import faulthandler
import gc
import socket
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import QApplication

from n1mm_scope_bridge import __version__
from n1mm_scope_bridge import settings as settings_mod
from n1mm_scope_bridge.gui.main_window import APP_TITLE, MainWindow
from n1mm_scope_bridge.gui.style import apply_style
from n1mm_scope_bridge.pipeline import PipelineStats

SELF_TEST_TIMEOUT_S = 15.0
SELF_TEST_PACKETS = 3
WATCHDOG_STALL_S = 2.0  # the GUI thread's stack is dumped once a loop pass takes longer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="n1mm-scope-bridge-gui", description=APP_TITLE)
    parser.add_argument("--settings", type=Path, help="settings file (default: per-user file)")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="open the window, stream the emulator to a local listener, and exit 0 on success",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        metavar="DIR",
        help="save website screenshots of the window and dialogs into DIR, then exit",
    )
    parser.add_argument(
        "--source",
        choices=("emulator", "radio", "replay"),
        default="emulator",
        help="with --screenshot/--record: the built-in emulator (default), the radio, "
        "or (--record only) a capture given with --replay",
    )
    parser.add_argument(
        "--ftdi-lib-dir", help="with --source radio: folder containing LibFT4222 and D2XX"
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=20.0,
        metavar="SECONDS",
        help="with --source radio: stream this long first so the waterfall fills (default 20)",
    )
    parser.add_argument(
        "--record",
        type=Path,
        metavar="DIR",
        help="record a video (MP4/WebM) and GIF of the streaming window into DIR, then exit",
    )
    parser.add_argument(
        "--replay", type=Path, help="with --record --source replay: capture recorded from a radio"
    )
    parser.add_argument(
        "--seconds", type=float, default=15.0, help="with --record: length of the recording"
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="with --record: frames per second (default: the source's own rate, about 11)",
    )
    parser.add_argument(
        "--format",
        action="append",
        choices=("mp4", "webm", "gif"),
        help="with --record: output format; repeat for several (default: mp4, webm and gif)",
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
    gc.collect()  # collect leftovers on the GUI thread, not in a pipeline thread (#219)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rx:
        rx.bind(("127.0.0.1", 0))
        rx.setblocking(False)
        settings = settings_mod.Settings(
            emulator=True, n1mm_host="127.0.0.1", n1mm_port=rx.getsockname()[1], rate_hz=10.0
        )
        window = MainWindow(settings, settings_path=settings_path)
        stats: list[PipelineStats] = []  # every POLL_MS; the last one explains a failure
        window.controller.stats.connect(stats.append)
        stops: list[str] = []  # why streaming stopped; "" is a normal stop (#219)
        window.controller.stopped.connect(stops.append)
        window.show()
        window.toggle_streaming()
        packets = 0
        slowest = 0.0  # the longest processEvents() call: a blocked GUI thread (#219)
        deadline = time.monotonic() + SELF_TEST_TIMEOUT_S
        with _Watchdog() as watchdog:
            while time.monotonic() < deadline and packets < SELF_TEST_PACKETS:
                watchdog.tick()
                started = time.monotonic()
                app.processEvents()
                slowest = max(slowest, time.monotonic() - started)
                received = _receive(rx, 1)
                packets += received
                if not received:
                    time.sleep(0.02)
        late = _receive(rx, 50)  # sent but never read: the loop ran out of time (#219)
        status_ok = window.status.text().startswith(("VFO", "Streaming"))
        threads = sorted(
            t.name
            for t in threading.enumerate()
            if t is not threading.main_thread() and t.name != _Watchdog.NAME
        )
        stacks = _thread_stacks() if packets < SELF_TEST_PACKETS else ""
        errors = [e for e in (*stops, window.model.last_error) if e]
        window.quit_app()  # never prompts, even when a system tray exists
        app.processEvents()
    gc.collect()
    if packets < SELF_TEST_PACKETS:
        pipeline = _describe_stats(stats[-1] if stats else None)
        running = ", ".join(threads) or "none"
        error = "; errors: " + " | ".join(dict.fromkeys(errors)) if errors else ""
        return False, (
            f"self-test: received {packets} N1MM packets, expected {SELF_TEST_PACKETS} "
            f"({pipeline}; threads: {running}; slowest processEvents: {slowest:.2f} s; "
            f"late packets: {late}{error})\n\n{watchdog.stack}{stacks}"
        ).rstrip()
    if not status_ok:
        return False, f"self-test: status line not updated ({window.status.text()!r})"
    return True, f"self-test: OK ({packets} packets, style {app.property('bridgeStyle')})"


def _receive(rx: socket.socket, limit: int) -> int:
    """Read up to ``limit`` queued datagrams without blocking; count the N1MM packets."""
    count = 0
    for _ in range(limit):
        try:
            count += int(b"<Spectrum>" in rx.recv(65535))
        except BlockingIOError:
            break
    return count


class _Watchdog:
    """Saves the GUI thread's stack once if the self-test loop stops ticking (#219)."""

    NAME = "selftest-watchdog"

    def __init__(self) -> None:
        self.stack = ""  # read only after the thread is joined
        self._main = threading.get_ident()
        self._lock = threading.Lock()
        self._last = time.monotonic()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=self.NAME)

    def __enter__(self) -> _Watchdog:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()

    def tick(self) -> None:
        with self._lock:
            self._last = time.monotonic()

    def _run(self) -> None:
        while not self._stop.wait(WATCHDOG_STALL_S / 4):
            with self._lock:
                idle = time.monotonic() - self._last
            frame = sys._current_frames().get(self._main) if idle > WATCHDOG_STALL_S else None
            if frame is not None:
                stack = "".join(traceback.format_stack(frame)).replace(str(Path.home()), "~")
                self.stack = f"GUI thread blocked for {idle:.2f} s at:\n{stack}\n"
                return


def _thread_stacks() -> str:
    """Every thread's stack, for a stalled self-test (#219); home folder shown as ``~``."""
    with tempfile.TemporaryFile() as dump:  # faulthandler needs a real file descriptor
        faulthandler.dump_traceback(dump, all_threads=True)
        dump.seek(0)
        text = dump.read().decode("utf-8", "replace")
    return text.replace(str(Path.home()), "~")


def _describe_stats(stats: PipelineStats | None) -> str:
    """Which pipeline stage stalled: frames read, dropped, bad, and sent (#209)."""
    if stats is None:
        return "no pipeline stats"
    return (
        f"read {stats.frames_read}, dropped {stats.frames_dropped}, "
        f"bad {stats.bad_frames}, sent {stats.emitted}"
    )


def _write_self_test_log(path: Path, message: str) -> None:
    """Keep the result where the installer smoke test can read it (#209).

    The windowed exe has no console, so its stdout and stderr are lost.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(message + "\n", encoding="utf-8")
    except OSError:
        pass  # best effort: the exit code still reports the result


def _record(args: argparse.Namespace, app: QApplication) -> int:
    """``--record DIR``: animated recording of the streaming window (website, #124)."""
    try:
        from n1mm_scope_bridge.gui import recording  # noqa: PLC0415 - needs Pillow (dev only)
    except ImportError:
        print("error: --record needs Pillow: uv sync (it is in the gui-dev group)", file=sys.stderr)
        return 1
    try:
        feed = None
        if args.source == "radio":
            feed = recording.radio_feed(args.ftdi_lib_dir)
        elif args.source == "replay":
            if args.replay is None:
                raise ValueError("--source replay needs --replay CAPTURE")
            feed = recording.replay_feed(args.replay)
        formats = tuple(dict.fromkeys(args.format)) if args.format else recording.FORMATS
        entry = recording.record(
            args.record, app, feed, seconds=args.seconds, fps=args.fps, formats=formats
        )
    except (ValueError, OSError, RuntimeError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(f"Saved {entry['file']} ({entry['frames']} frames) to {args.record}: {entry['bytes']}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = application()
    if args.record is not None:
        return _record(args, app)
    if args.screenshot is not None:
        from n1mm_scope_bridge.gui import screenshot  # noqa: PLC0415 - only for this mode

        source = None
        if args.source == "radio":
            try:
                source = screenshot.radio_source(args.ftdi_lib_dir, args.settle)
            except (ValueError, OSError, RuntimeError) as err:
                print(f"error: {err}", file=sys.stderr)
                return 1
        paths = screenshot.capture(args.screenshot, app, source=source)
        print(f"Saved {len(paths)} screenshots to {args.screenshot}")
        return 0
    if args.self_test:
        path = args.settings or Path(settings_mod.settings_path().parent / "self-test.json")
        ok, message = self_test(app, path)
        print(message, file=sys.stdout if ok else sys.stderr)
        _write_self_test_log(path.with_name("self-test.log"), message)
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
