# `ctl`: control a running bridge

```
n1mm-scope-bridge ctl [--host HOST] [--port PORT] [--timeout SECONDS] REQUEST...
```

Sends one [remote-control](../udp-control.md) command to a bridge that is
running with remote control enabled, prints the JSON reply, and exits `0` if
the reply says `"ok": true`, otherwise `1`.

| Option | Default | Meaning |
|---|---|---|
| `--host HOST` | `127.0.0.1` | PC running the bridge |
| `--port PORT` | `13070` | Remote-control port |
| `--timeout SECONDS` | `2` | How long to wait for a reply |
| `REQUEST` | required | `status`, `start`, `stop`, `ping`, `help`, or `set name|rate|combine|scaling VALUE` |

Examples:

```
n1mm-scope-bridge ctl status
n1mm-scope-bridge ctl stop
n1mm-scope-bridge ctl set rate 5
```
