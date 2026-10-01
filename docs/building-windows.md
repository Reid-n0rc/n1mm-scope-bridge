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
