# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Is the radio's FT4222H present in Windows without a working driver? (issue #152).

When opening the scope interface fails, this lets the error say *why*: the
device is plugged in but Windows has no FTDI driver for it, as opposed to the
radio being off or SCU-LAN10 being OFF. Best effort and read-only: it runs
`pnputil /enum-devices /connected` (Windows 10 2004 and later) and never needs
administrator rights. Anywhere else, or if pnputil fails, the answer is "unknown".
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Literal

DriverState = Literal["ok", "no-driver", "not-present", "unknown"]
Runner = Callable[[Sequence[str]], tuple[int, str]]

FT4222_HARDWARE_ID = "USB\\VID_0403&PID_601C"
DRIVER_HINT = (
    "Windows sees the radio's scope interface (FT4222H) but has no working FTDI USB "
    'driver for it. Run the installer again and tick "Install FTDI USB driver (needs '
    'administrator)", or let Windows Update install it, then unplug and replug the USB cable.'
)


def _pnputil() -> str:
    root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    for sub in ("System32", "Sysnative"):
        path = os.path.join(root, sub, "pnputil.exe")
        if os.path.exists(path):
            return path
    return "pnputil.exe"


def run_command(cmd: Sequence[str]) -> tuple[int, str]:  # pragma: no cover - Windows only
    proc = subprocess.run(
        list(cmd), capture_output=True, text=True, check=False, timeout=15, errors="replace"
    )
    return proc.returncode, proc.stdout + proc.stderr


def parse_devices(output: str) -> list[dict[str, str]]:
    """Split `pnputil /enum-devices` output into one dict of fields per device."""
    devices: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        if key == "instance id":
            if current:
                devices.append(current)
            current = {}
        if current or key == "instance id":
            current[key] = value.strip()
    if current:
        devices.append(current)
    return devices


def classify(devices: list[dict[str, str]]) -> DriverState:
    ours = [d for d in devices if d.get("instance id", "").upper().startswith(FT4222_HARDWARE_ID)]
    if not ours:
        return "not-present"
    if any(d.get("status", "").lower() == "started" and d.get("driver name") for d in ours):
        return "ok"
    if any("problem code" in d or not d.get("driver name") for d in ours):
        return "no-driver"
    return "unknown"


def ft4222_driver_state(
    runner: Runner = run_command, *, windows: bool = sys.platform == "win32"
) -> DriverState:
    if not windows:
        return "unknown"
    try:
        code, out = runner([_pnputil(), "/enum-devices", "/connected"])
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if code != 0:
        return "unknown"
    return classify(parse_devices(out))


def driver_hint(runner: Runner = run_command, *, windows: bool = sys.platform == "win32") -> str:
    """The hint to add to a "Could not open" error, or "" when it doesn't apply."""
    return DRIVER_HINT if ft4222_driver_state(runner, windows=windows) == "no-driver" else ""
