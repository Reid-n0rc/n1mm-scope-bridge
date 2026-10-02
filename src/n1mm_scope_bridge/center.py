# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Center scope mode: prompt the operator and confirm it from the scope frames (#62).

The bridge never changes the scope mode itself and never opens a COM port:
N1MM+ needs both FT-710 COM ports (Enhanced for CAT, Standard for PTT). The
mode the radio is in arrives in every scope frame (status byte 17), so the
bridge asks the operator to choose Center, confirms when it is set, and offers
N1MM+ function-key macros ("Scope Center", "Scope restore") that N1MM+ sends
over its own CAT port when the operator presses them.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from n1mm_scope_bridge.radios.base import ScopeStatus

# FT-710 "Scope Mode" CAT command (wfview rigs/FT-710.rig command 68, "SS06",
# 5 parameter bytes padded right with 0; Yaesu FTDX10 CAT manual: SS P1=0 P2=6
# P3=mode P4-P7=0). UNVERIFIED (#62): exact parameter format on the FT-710.
# N1MM+ sends these from its own CAT port; the bridge never sends CAT.
CENTER_CODE = "4"  # Center (Normal)
MODE_CODES = "0123456789AB"


def scope_mode_cat(code: str) -> str:
    """The CAT string that sets the scope mode, for example ``SS0640000;``."""
    if len(code) != 1 or code.upper() not in MODE_CODES:
        raise ValueError(f"scope mode code must be one of {', '.join(MODE_CODES)}, got {code!r}")
    return f"SS06{code.upper()}0000;"


def n1mm_macros(restore_code: str | None) -> list[tuple[str, str]]:
    """N1MM+ function-key macros as (label, text), ready to paste in the F-key editor.

    "Scope Center" switches to Center (Normal); "Scope restore" goes back to
    ``restore_code`` (the mode seen when streaming started), if known.
    """
    macros = [("Scope Center", f"{{CAT1ASC {scope_mode_cat(CENTER_CODE)}}}")]
    if restore_code is not None and restore_code.upper() != CENTER_CODE:
        macros.append(("Scope restore", f"{{CAT1ASC {scope_mode_cat(restore_code)}}}"))
    return macros


def format_macros(macros: list[tuple[str, str]]) -> str:
    """One ``Label,text`` line per macro, the N1MM+ function-key file format."""
    return "\n".join(f"{label},{text}" for label, text in macros)


PROMPT = (
    "Set the {model}'s scope to Center mode for exact N1MM+ frequencies "
    "(currently {mode}). Streaming continues meanwhile."
)
CONFIRMED = "{model} scope is in Center mode: N1MM+ frequencies are exact."
LEFT = "{model} scope left Center mode ({mode}); N1MM+ frequencies are approximate."
MACRO_HINT = "\nN1MM+ function-key macros (paste into the F-key editor; UNVERIFIED #62):\n"


class CenterModeMonitor:
    """Turns scope-mode changes into one-time operator messages (thread-safe).

    ``observe`` runs on the pipeline's sender thread. Messages: a prompt when
    the scope is not in Center, a confirmation once it is (only after a
    prompt), and a notice if it leaves Center again.
    """

    def __init__(self, model: str, notify: Callable[[str], object]) -> None:
        self._model = model
        self._notify = notify
        self._lock = threading.Lock()
        self._centered: bool | None = None
        self.prompted = False
        self.start_code: str | None = None
        """Scope mode code at stream start (status byte 17), for the restore macro."""

    def macros(self) -> list[tuple[str, str]]:
        """N1MM+ "Scope Center" / "Scope restore" macros (API for the GUI's Copy buttons)."""
        with self._lock:
            return n1mm_macros(self.start_code)

    def observe(self, status: ScopeStatus) -> None:
        centered = status.mode_family == "center"
        with self._lock:
            if self.start_code is None:
                code = getattr(status, "scope_mode_code", None)
                self.start_code = code if isinstance(code, str) else None
            previous, self._centered = self._centered, centered
            if previous == centered:
                return
            if not centered:
                first = not self.prompted
                template = LEFT if previous else PROMPT
                self.prompted = True
                message = template.format(model=self._model, mode=status.mode_name)
                if first:
                    message += MACRO_HINT + format_macros(n1mm_macros(self.start_code))
            elif self.prompted:
                message = CONFIRMED.format(model=self._model)
            else:
                return  # already in Center from the start: nothing to say
        self._notify(message)
