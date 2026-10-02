# Command line

The GUI is the normal way to run the bridge. Everything it does can also be
done from a Command Prompt or PowerShell, which is useful for scripts,
headless station PCs, and troubleshooting.

```
n1mm-scope-bridge [--version] [--license] COMMAND [options]
```

| Global option | Meaning |
|---|---|
| `--version` | Print the version, copyright, and license notice |
| `--license` | Print the full license and warranty terms and where to get the source |
| `-h`, `--help` | Show help (also works after each command: `n1mm-scope-bridge run --help`) |

Exit codes: `0` success; `1` a problem you can fix (the message says what);
`2` invalid command-line usage.

## Commands

Each command has its own page in the [`cli/`](cli/) folder, named after the
command: for example [`run`](cli/run.md) streams the scope to N1MM+,
[`probe`](cli/probe.md) checks the setup, and `n1mm-scope-bridge --help`
lists every command.
