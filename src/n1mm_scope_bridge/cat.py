# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Optional "Center scope mode while streaming" (#62, docs/design/scope-center-mode.md).

The only radio-state change the bridge ever makes, and only when the operator
turns on ``force_center_mode`` (off by default). ``CatControl`` can do exactly
one thing, set the scope mode, so nothing else (and nothing that transmits)
can be sent through it.

CAT command (Yaesu ``SS`` / P2=6, wfview rigs/FT-710.rig "Scope Mode"):
``SS06<code>0000;``. UNVERIFIED (#62) on the FT-710 itself.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from n1mm_scope_bridge.radios.base import ScopeStatus

CENTER = "4"  # Center (Normal) on the FT-710
MODE_CODES = "0123456789AB"


def scope_mode_command(code: str) -> str:
    """The CAT string that sets the scope mode, for example ``SS0640000;``."""
    if len(code) != 1 or code.upper() not in MODE_CODES:
        raise ValueError(f"scope mode code must be one of {', '.join(MODE_CODES)}, got {code!r}")
    return f"SS06{code.upper()}0000;"


class CatControl(Protocol):
    def set_scope_mode(self, code: str) -> None:
        """Set the radio's scope mode (raise OSError or ValueError on failure)."""


class EmulatorCat:
    """``CatControl`` for the FT-710 emulator: the next frames show the new mode."""

    def __init__(self, emulator: object) -> None:
        self._emulator = emulator
        self.commands: list[str] = []

    def set_scope_mode(self, code: str) -> None:
        self.commands.append(scope_mode_command(code))
        self._emulator.set_scope_mode(int(code, 16))  # type: ignore[attr-defined]


def mode_code(status: ScopeStatus) -> str | None:
    code = getattr(status, "scope_mode_code", None)
    return code if isinstance(code, str) else None


class ScopeModeKeeper:
    """Switches the scope to Center for a session and restores the operator's mode.

    ``observe`` runs on the pipeline's sender thread for every status; ``restore``
    runs when the session ends. Never fights the operator: if the scope leaves
    Center after we set it, the keeper stops managing and won't restore.
    """

    def __init__(
        self,
        cat: CatControl,
        warn: Callable[[str], object] = print,
        center: str = CENTER,
    ) -> None:
        self._cat = cat
        self._warn = warn
        self._center = center
        self._lock = threading.Lock()
        self.original: str | None = None
        self.set_by_us = False
        self.confirmed = False
        self.abandoned = False

    def observe(self, status: ScopeStatus) -> None:
        code = mode_code(status)
        if code is None:
            return
        with self._lock:
            if self.original is None:
                self.original = code
                if code != self._center:
                    self._send(self._center)
                    self.set_by_us = not self.abandoned
                return
            if not self.set_by_us or self.abandoned:
                return
            if code == self._center:
                self.confirmed = True
            elif self.confirmed:
                self.abandoned = True  # the operator chose another mode: leave it alone

    def restore(self) -> None:
        with self._lock:
            if self.set_by_us and not self.abandoned and self.original is not None:
                self._send(self.original)
            self.set_by_us = False

    def _send(self, code: str) -> None:
        try:
            self._cat.set_scope_mode(code)
        except (OSError, ValueError) as err:
            self.abandoned = True
            self._warn(f"Could not change the scope mode ({err}); leaving it as it is.")
