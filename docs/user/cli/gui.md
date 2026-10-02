# `gui`

Opens the N1MM Scope Bridge window, the same as the **N1MM Scope Bridge**
shortcut or `n1mm-scope-bridge-gui`. See the [GUI guide](../gui.md).

```
n1mm-scope-bridge gui [--settings PATH] [--self-test]
```

| Option | Default | Meaning |
|---|---|---|
| `--settings PATH` | the per-user settings file | Use a different settings file |
| `--self-test` | off | Open the window, stream the built-in emulator to a local test listener, and exit with code 0 on success |

The window needs the optional GUI package (PySide6). The Windows installer
includes it. With pip: `pip install "n1mm-scope-bridge[gui]"`.
