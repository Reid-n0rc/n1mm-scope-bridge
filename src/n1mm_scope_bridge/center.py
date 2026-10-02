# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Center scope mode: prompt the operator and confirm it from the scope frames (#62).

The bridge never changes the scope mode itself and never opens a COM port:
N1MM+ needs both FT-710 COM ports (Enhanced for CAT, Standard for PTT). The
mode the radio is in arrives in every scope frame (status byte 17), so the
bridge asks the operator to choose Center and confirms when it is set.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from n1mm_scope_bridge.radios.base import ScopeStatus

PROMPT = (
    "Set the {model}'s scope to Center mode for exact N1MM+ frequencies "
    "(currently {mode}). Streaming continues meanwhile."
)
CONFIRMED = "{model} scope is in Center mode: N1MM+ frequencies are exact."
LEFT = "{model} scope left Center mode ({mode}); N1MM+ frequencies are approximate."


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

    def observe(self, status: ScopeStatus) -> None:
        centered = status.mode_family == "center"
        with self._lock:
            previous, self._centered = self._centered, centered
            if previous == centered:
                return
            if not centered:
                template = LEFT if previous else PROMPT
                self.prompted = True
                message = template.format(model=self._model, mode=status.mode_name)
            elif self.prompted:
                message = CONFIRMED.format(model=self._model)
            else:
                return  # already in Center from the start: nothing to say
        self._notify(message)
