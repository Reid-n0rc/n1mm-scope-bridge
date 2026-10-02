# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Status presenter, bounded log, and diagnostics text for the GUI (#28).

Pure Python (no widgets) so it is fully testable without a display.
"""

from __future__ import annotations

import ipaddress
import json
import platform
import re
import socket
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from n1mm_scope_bridge import __version__
from n1mm_scope_bridge.pipeline import PipelineStats
from n1mm_scope_bridge.radios import get_radio
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


REDACTED_HOST = "<redacted host>"
REDACTED_IP = "<redacted IP>"
REDACTED_NAME = "<redacted source name>"
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IPV6 = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])")


def _is_loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return address.lower() == "localhost"


def redact_network(text: str, hostname: str | None = None) -> str:
    """Replace non-loopback IP addresses and this PC's host name (GDPR: personal data)."""

    def ip(match: re.Match[str]) -> str:
        value = match.group(0)
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return value  # not an address (e.g. a time like 12:34:56)
        return value if _is_loopback(value) else REDACTED_IP

    text = _IPV6.sub(ip, _IPV4.sub(ip, text))
    host = socket.gethostname() if hostname is None else hostname
    if host and host.lower() not in ("localhost", ""):
        text = re.sub(re.escape(host), REDACTED_HOST, text, flags=re.IGNORECASE)
    return text


def _private_settings(settings: Settings, include_identity: bool) -> dict[str, object]:
    data = settings.to_dict()
    for key in ("n1mm_host", "control_bind"):
        value = str(data.get(key, ""))
        if value and not _is_loopback(value):
            data[key] = REDACTED_HOST
    if data.get("control_allow"):
        data["control_allow"] = REDACTED_IP
    if (
        data.get("source_name")
        and not include_identity
        and data["source_name"] != _radio_model(settings)
    ):
        data["source_name"] = REDACTED_NAME
    return data


def diagnostics(
    settings: Settings,
    model: StatusModel,
    log: LogBuffer,
    *,
    home: PurePath | None = None,
    hostname: str | None = None,
    include_identity: bool = False,
) -> str:
    """Text for bug reports: version, platform, settings, status, recent log.

    Privacy by design: the user's home folder, non-loopback IP addresses, this
    PC's host name and the N1MM+ source name (often a call sign) are redacted
    unless ``include_identity`` is set (the operator's explicit choice).
    """
    stats = model.stats
    lines = [
        f"n1mm-scope-bridge {__version__}",
        f"Python {platform.python_version()} on {platform.system()} {platform.release()}",
        "",
        "Settings:",
        json.dumps(_private_settings(settings, include_identity), indent=2, sort_keys=True),
        "",
        "Status:",
        *(f"  {label}: {value}" for label, value in model.rows()),
        f"  Frames read: {stats.frames_read if stats else 0}",
        "",
        f"Log (last {DIAGNOSTIC_LOG_LINES} lines):",
        *log.lines()[-DIAGNOSTIC_LOG_LINES:],
    ]
    text = redact_network(redact_home("\n".join(lines), home), hostname)
    name = settings.source_name.strip()
    # A source name equal to the radio model ("FT-710") identifies nobody; keep it.
    if name and not include_identity and name != _radio_model(settings):
        text = text.replace(name, REDACTED_NAME)
    return text


def _radio_model(settings: Settings) -> str:
    try:
        return get_radio(settings.radio).model
    except KeyError:
        return ""
