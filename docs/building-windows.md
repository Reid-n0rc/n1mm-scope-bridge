# Building the Windows app

The Windows app is a PyInstaller **one-folder** build. It starts faster and
triggers fewer antivirus false positives than a one-file build, and it keeps
the Qt libraries as separate, replaceable DLLs.

```
uv sync --group packaging
uv run --group packaging python scripts/build_windows_app.py
```

Output: `dist/windows/n1mm-scope-bridge/` and
`dist/windows/n1mm-scope-bridge-<version>-win64.zip`, containing:

- `n1mm-scope-bridge.exe`, the command line;
- `N1MM Scope Bridge.exe`, the windowed GUI (built automatically once
  `n1mm_scope_bridge.gui.app` exists, issue #18; force it with
  `--gui on` or `--gui off`);
- `licenses/` with `LICENSE`, `NOTICE`, `THIRD_PARTY.md`, and the Qt license
  texts when the GUI is bundled.

The script fails if any FTDI LibFT4222 or ftd2xx binary ends up in the
build; those are never shipped. It then smoke-tests the built executable:
`--version` and `--license` must show the GPL notices, and
`run --emulator --duration 2` must stream `<Spectrum>` packets to a local UDP
listener. Use `--no-smoke` to skip that.

CI builds the app on `windows-latest` (workflow **Windows app**) for PRs that
can change it, and uploads the zip as the `windows-app` artifact. On macOS or
Linux, `--allow-non-windows` builds a native development app with the same
steps.

## Installer

`packaging/windows/installer.iss` (Inno Setup 7) wraps the one-folder app
into `n1mm-scope-bridge-setup-<version>.exe`:

```
uv run --no-project python scripts/build_installer.py [--iscc "C:\path\to\ISCC.exe"]
```

- Installs per user by default (no admin prompt); the dialog offers an
  all-users install.
- Creates a Start menu shortcut (plus the setup guide and licenses), an
  optional desktop shortcut, and an optional *Start with Windows* entry.
- Shows the GPL license page and installs `licenses/`.
- **FTDI LibFT4222 is never included.** If it isn't in `System32`, a wizard
  page explains why, offers FTDI's download page, and can copy
  `LibFT4222-64.dll` (and `ftd2xx.dll`) from a folder **the user** downloaded
  into the program folder. Those copies are removed on uninstall.
- Uninstall keeps the settings unless the user asks to remove them (silent
  uninstall always keeps them).

The **Windows installer** workflow builds the app and the installer on
`windows-latest`, then runs `packaging/windows/smoke_test.ps1`:
1. silent per-user install into a temp folder;
2. check the files, shortcuts, uninstall entry, and that there are no FTDI DLLs;
3. run the installed CLI (`--version`, then emulator frames into UDP) and the
   GUI `--self-test`;
4. silent uninstall, then check everything is removed except the settings.

Inno Setup is downloaded from its GitHub release and pinned by SHA-256 in the
workflow.

The installer is not code-signed yet, so Windows SmartScreen will warn on
first run. Code signing is a follow-up.
