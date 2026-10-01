# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Persistent operator settings, shared by the GUI and the CLI.

Stored as JSON in the per-user config folder
(``%APPDATA%\\n1mm-scope-bridge\\settings.json`` on Windows). Writes are
atomic, unknown keys are ignored, and a corrupt file is backed up and replaced
with defaults instead of stopping the program.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal, get_args

from n1mm_scope_bridge.bridge import (
    COMBINE_MODES,
    DEFAULT_RATE_HZ,
    DEFAULT_SCALING,
    BridgeConfig,
)
from n1mm_scope_bridge.n1mm import DEFAULT_HOST, DEFAULT_PORT
from n1mm_scope_bridge.radios import get_radio
from n1mm_scope_bridge.transport.ft4222 import DEFAULT_DESCRIPTION

APP_DIR = "n1mm-scope-bridge"
SCHEMA_VERSION = 1
OnClose = Literal["ask", "tray", "exit"]
ON_CLOSE_CHOICES: tuple[str, ...] = get_args(OnClose)


@dataclass(frozen=True)
class Settings:
    radio: str = "ft710"
    source_name: str = ""
    """Name shown in N1MM+; empty means the radio model (for example "FT-710")."""
    n1mm_host: str = DEFAULT_HOST
    n1mm_port: int = DEFAULT_PORT
    rate_hz: float = DEFAULT_RATE_HZ
    scaling: float = DEFAULT_SCALING
    combine: str = "latest"
    ftdi_lib_dir: str = ""
    device: str = DEFAULT_DESCRIPTION
    start_streaming_on_launch: bool = False
    start_minimized: bool = False
    on_close: str = "ask"
    """What the window's Close button does: ask, tray (keep streaming), or exit."""

    def effective_name(self) -> str:
        if self.source_name:
            return self.source_name
        try:
            return get_radio(self.radio).model
        except KeyError:
            return self.radio

    def validate(self) -> dict[str, str]:
        """Field name -> problem, for every invalid field (empty when valid)."""
        problems: dict[str, str] = {}
        try:
            profile = get_radio(self.radio)
        except KeyError as err:
            problems["radio"] = str(err.args[0])
            profile = None
        if self.source_name != self.source_name.strip():
            problems["source_name"] = "remove leading or trailing spaces"
        if not self.n1mm_host.strip():
            problems["n1mm_host"] = (
                "enter the N1MM+ PC's name or IP address (127.0.0.1 for this PC)"
            )
        if not 0 < self.n1mm_port < 65536:
            problems["n1mm_port"] = "port must be 1-65535 (N1MM+ uses 13064)"
        if not 0 < self.rate_hz <= 10:
            problems["rate_hz"] = "updates per second must be more than 0 and at most 10"
        if not self.scaling > 0:
            problems["scaling"] = "scaling must be greater than 0"
        if self.combine not in COMBINE_MODES:
            problems["combine"] = f"choose one of: {', '.join(COMBINE_MODES)}"
        if self.on_close not in ON_CLOSE_CHOICES:
            problems["on_close"] = f"choose one of: {', '.join(ON_CLOSE_CHOICES)}"
        if self.ftdi_lib_dir and not os.path.isdir(self.ftdi_lib_dir):
            problems["ftdi_lib_dir"] = "folder does not exist"
        if profile is not None and not problems:
            try:
                self.to_bridge_config()
            except ValueError as err:
                problems["source_name"] = str(err)
        return problems

    def to_bridge_config(self) -> BridgeConfig:
        return BridgeConfig(
            get_radio(self.radio),
            self.effective_name(),
            scaling=self.scaling,
            rate_hz=self.rate_hz,
            combine=self.combine,  # type: ignore[arg-type]  # validated by BridgeConfig
        )

    def replace(self, **changes: Any) -> Settings:
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {"version": SCHEMA_VERSION, **dataclasses.asdict(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> tuple[Settings, list[str]]:
        """Build settings from stored data. Unknown keys are ignored; wrong types fall
        back to the default with a warning."""
        warnings: list[str] = []
        values: dict[str, Any] = {}
        defaults = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value, default = data[f.name], getattr(defaults, f.name)
            if isinstance(default, bool):
                ok = isinstance(value, bool)
            elif isinstance(default, float):
                ok = isinstance(value, int | float) and not isinstance(value, bool)
                value = float(value) if ok else value
            elif isinstance(default, int):
                ok = isinstance(value, int) and not isinstance(value, bool)
            else:
                ok = isinstance(value, str)
            if ok:
                values[f.name] = value
            else:
                warnings.append(f"ignored invalid {f.name!r} in settings; using {default!r}")
        return cls(**values), warnings


def settings_path(
    env: Mapping[str, str] | None = None, platform: str = sys.platform, home: Path | None = None
) -> Path:
    """Per-user settings file location."""
    env = os.environ if env is None else env
    home = home or Path.home()
    if platform == "win32":
        base = Path(env["APPDATA"]) if env.get("APPDATA") else home / "AppData" / "Roaming"
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else home / ".config"
    return base / APP_DIR / "settings.json"


def load(path: Path | None = None) -> tuple[Settings, list[str]]:
    """Load settings, returning defaults (plus a warning) if the file is unusable."""
    path = path or settings_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings(), []
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except ValueError as err:
        backup = path.with_suffix(path.suffix + ".bak")
        os.replace(path, backup)
        return Settings(), [f"settings file was unreadable ({err}); saved a copy as {backup.name}"]
    return Settings.from_dict(data)


def save(settings: Settings, path: Path | None = None) -> Path:
    """Write settings atomically (a crash never leaves a truncated file)."""
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(settings.to_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path
