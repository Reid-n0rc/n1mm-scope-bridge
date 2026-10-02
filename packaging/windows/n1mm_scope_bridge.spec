# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
# PyInstaller spec: one-folder Windows build (issue #6).
#
# Run through scripts/build_windows_app.py, which sets:
#   N1MM_BUILD_GUI=1      also build the windowed "N1MM Scope Bridge.exe" and
#                         bundle PySide6 (only once n1mm_scope_bridge.gui.app
#                         exists, issue #18); otherwise PySide6 is excluded
#   N1MM_VERSION_FILE     Windows version resource generated from __version__
#   N1MM_ICON (optional)  .ico for the executables (provided by the GUI lane)
#
# FTDI's LibFT4222/ftd2xx are never bundled; the build script fails if any
# appear in the output.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIR = Path(SPECPATH)  # noqa: F821 - provided by PyInstaller
ROOT = SPEC_DIR.parent.parent
BUILD_GUI = os.environ.get("N1MM_BUILD_GUI") == "1"
VERSION_FILE = os.environ.get("N1MM_VERSION_FILE")
ICON = os.environ.get("N1MM_ICON") or None

# Commands and radios are discovered at run time, so collect every submodule.
hidden = collect_submodules(
    "n1mm_scope_bridge", filter=lambda name: BUILD_GUI or ".gui" not in name
)
excludes = ["tkinter"] + ([] if BUILD_GUI else ["PySide6", "shiboken6"])


def analysis(script):
    return Analysis(  # noqa: F821
        [str(SPEC_DIR / script)],
        pathex=[str(ROOT / "src")],
        hiddenimports=hidden,
        excludes=excludes,
        noarchive=False,
    )


cli = analysis("entry_cli.py")
cli_exe = EXE(  # noqa: F821
    PYZ(cli.pure),  # noqa: F821
    cli.scripts,
    exclude_binaries=True,
    name="n1mm-scope-bridge",
    console=True,
    version=VERSION_FILE,
    icon=ICON,
)
parts = [cli_exe, cli.binaries, cli.datas]

if BUILD_GUI:
    gui = analysis("entry_gui.py")
    gui_exe = EXE(  # noqa: F821
        PYZ(gui.pure),  # noqa: F821
        gui.scripts,
        exclude_binaries=True,
        name="N1MM Scope Bridge",
        console=False,
        version=VERSION_FILE,
        icon=ICON,
    )
    parts += [gui_exe, gui.binaries, gui.datas]

COLLECT(*parts, name="n1mm-scope-bridge")  # noqa: F821
