# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Status presenter, bounded log, and diagnostics text for the GUI (#28).

Pure Python (no widgets) so it is fully testable without a display.
"""

from __future__ import annotations

import json
import platform
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from n1mm_scope_bridge import __version__
from n1mm_scope_bridge.pipeline import PipelineStats
from n1mm_scope_bridge.radios.base import ScopeStatus
from n1mm_scope_bridge.settings import Settings

LOG_LINES = 500
DIAGNOSTIC_LOG_LINES = 50


@dataclass
class StatusModel:
    """What the status panel shows; updated from controller signals."""

    clock: Callable[[], float] = time.monotonic
    streaming: bool = False
    status: ScopeStatus | None = None
    stats: PipelineStats | None = None
    rate_per_s: float = 0.0
    last_error: str = ""
    _last_sample: tuple[float, int] | None = field(default=None, repr=False)

    def started(self) -> None:
        self.streaming = True
        self.status = None
        self.stats = None
        self.rate_per_s = 0.0
        self.last_error = ""
        self._last_sample = None

    def stopped(self, error: str) -> None:
        self.streaming = False
        self.rate_per_s = 0.0
        if error:
            self.last_error = error

    def update_stats(self, stats: PipelineStats) -> None:
        now = self.clock()
        if self._last_sample is not None:
            then, sent = self._last_sample
            if now > then:
                self.rate_per_s = max(0.0, (stats.emitted - sent) / (now - then))
        self._last_sample = (now, stats.emitted)
        self.stats = stats

    def rows(self) -> list[tuple[str, str]]:
        """(label, value) pairs for the status panel."""
        s, st = self.status, self.stats
        radio = (
            "Receiving scope data"
            if s
            else ("Waiting for the radio" if self.streaming else "Not streaming")
        )
        return [
            ("Radio", radio),
            ("VFO", f"{s.vfo_hz / 1e6:.6f} MHz" if s else "—"),
            ("Span", f"{s.span_hz / 1e3:g} kHz" if s else "—"),
            ("Scope mode", self._mode_text()),
            (
                "Sent to N1MM+",
                f"{self.rate_per_s:.1f} per second ({st.emitted} total)" if st else "—",
            ),
            ("Dropped / bad frames", f"{st.frames_dropped} / {st.bad_frames}" if st else "—"),
            ("Last error", self.last_error or "None"),
        ]

    def _mode_text(self) -> str:
        if self.status is None:
            return "—"
        if self.status.edges_verified:
            return self.status.mode_name
        return f"{self.status.mode_name} (set Center for exact frequencies)"

    def summary(self, name: str) -> str:
        """One line for the tray tooltip."""
        if not self.streaming:
            return "Stopped" + (f" ({self.last_error})" if self.last_error else "")
        return f"Streaming {name} to N1MM+, {self.rate_per_s:.1f} per second"


class LogBuffer:
    """The last ``LOG_LINES`` messages, timestamped."""

    def __init__(self, limit: int = LOG_LINES, now: Callable[[], float] = time.time) -> None:
        self._lines: deque[str] = deque(maxlen=limit)
        self._now = now

    def add(self, level: str, message: str) -> str:
        line = f"{time.strftime('%H:%M:%S', time.localtime(self._now()))} {level}: {message}"
        self._lines.append(line)
        return line

    def lines(self) -> list[str]:
        return list(self._lines)


def redact_home(text: str, home: PurePath | None = None) -> str:
    """Replace the user's home folder (it contains the account name) with ``~``.

    Covers the plain form, the JSON-escaped form (``C:\\\\Users\\\\op`` in the
    settings dump), and the forward-slash form of a Windows path.
    """
    home_text = str(home if home is not None else Path.home())
    if home_text in ("", "/", "\\"):
        return text
    forms = {home_text, json.dumps(home_text)[1:-1], home_text.replace("\\", "/")}
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, "~")
    return text


def diagnostics(
    settings: Settings,
    model: StatusModel,
    log: LogBuffer,
    *,
    home: PurePath | None = None,
) -> str:
    """Text for bug reports: version, platform, settings, status, recent log."""
    stats = model.stats
    lines = [
        f"n1mm-scope-bridge {__version__}",
        f"Python {platform.python_version()} on {platform.platform()}",
        "",
        "Settings:",
        json.dumps(settings.to_dict(), indent=2, sort_keys=True),
        "",
        "Status:",
        *(f"  {label}: {value}" for label, value in model.rows()),
        f"  Frames read: {stats.frames_read if stats else 0}",
        "",
        f"Log (last {DIAGNOSTIC_LOG_LINES} lines):",
        *log.lines()[-DIAGNOSTIC_LOG_LINES:],
    ]
    return redact_home("\n".join(lines), home)
