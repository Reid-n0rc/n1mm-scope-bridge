# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""Regenerate tests/fixtures/ft710_synthetic.cap (deterministic demo frames).

uv run python scripts/make_synthetic_capture.py
"""

from __future__ import annotations

from pathlib import Path

from n1mm_scope_bridge.demo import demo_frames
from n1mm_scope_bridge.radios.ft710 import FT710
from n1mm_scope_bridge.transport.replay import CaptureWriter

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ft710_synthetic.cap"
FRAMES = 8


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("wb") as fh:
        writer = CaptureWriter(fh, FT710.model, FT710.frame_size)
        for frame in demo_frames(FRAMES):
            writer.write(frame)
    print(f"wrote {OUT} ({FRAMES} frames)")


if __name__ == "__main__":
    main()
