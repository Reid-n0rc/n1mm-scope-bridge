@echo off
rem SPDX-License-Identifier: GPL-3.0-only
rem SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
rem Start-menu shortcut for the 32-bit command-line version (issue #149).
title N1MM Scope Bridge (command line)
echo N1MM Scope Bridge (command line). The window (GUI) needs 64-bit Windows.
echo Streaming your radio's scope to N1MM+ with your saved settings. Press Ctrl+C to stop.
echo Options: "%~dp0n1mm-scope-bridge.exe" run --help    User guide: https://reid-n0rc.github.io/n1mm-scope-bridge/
echo.
"%~dp0n1mm-scope-bridge.exe" run --settings
echo.
pause
