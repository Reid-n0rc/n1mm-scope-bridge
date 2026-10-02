# UDP remote control

Other station software can start, stop, and adjust a running bridge, for
example an N1MM+ macro, a Stream Deck button, or a contest script.

**It is off by default.** Nothing listens on the network unless you turn it
on.

## Turning it on

- **GUI:** coming soon (#77).
- **Command line:** `n1mm-scope-bridge run --control-port 13070`
- **Settings file:** `"control_enabled": true` (see [settings](settings.md)).

The bridge then listens on **127.0.0.1 port 13070**, so only programs on this
PC can control it. To allow another PC, set `control_bind` to this PC's
address **and** list the allowed client IPs in `control_allow`. Requests from
any other address are ignored.

## Commands

Send one command per UDP datagram (plain text, any case). The bridge replies
to the sender with one line of JSON.

| Command | What it does | Reply (example) |
|---|---|---|
| `status` | Report the current state | `{"ok": true, "streaming": true, "radio": "FT-710", "vfo_hz": 14074000, "span_hz": 20000, "mode": "Center (Normal)", "sent": 412, "dropped": 0, "bad": 0, ...}` |
| `start` | Start streaming to N1MM+ | as `status` |
| `stop` | Stop streaming to N1MM+ (the program keeps running) | as `status` |
| `set name TEXT` | Change the source name shown in N1MM+ | `{"ok": true, "name": "Shack"}` |
| `set rate N` | Updates per second to N1MM+ (more than 0, at most 10) | `{"ok": true, "rate": 5.0}` |
| `set combine MODE` | `latest`, `average`, or `peak` | `{"ok": true, "combine": "peak"}` |
| `set scaling X` | dB per level step | `{"ok": true, "scaling": 0.25}` |
| `ping` | Check it is running | `{"ok": true, "version": "0.1.0"}` |
| `help` | List the commands | `{"ok": true, "help": "..."}` |

Errors look like `{"ok": false, "error": "rate must be ..."}`.

**Safety:** no command transmits, keys the radio, or changes any radio
setting. Remote control only affects what the bridge sends to N1MM+.

## Examples

Command line (from a batch file, for example):

```
n1mm-scope-bridge ctl status
n1mm-scope-bridge ctl set combine peak
```

**N1MM+ macro.** N1MM+ function-key macros can run a program with `{EXEC}`.
To make a key that stops the spectrum stream:

```
Stop scope,{EXEC n1mm-scope-bridge ctl stop}
```

PowerShell, without the bridge's command:

```powershell
$u = New-Object System.Net.Sockets.UdpClient
$u.Connect("127.0.0.1", 13070)
$b = [Text.Encoding]::UTF8.GetBytes("status"); [void]$u.Send($b, $b.Length)
$ep = New-Object System.Net.IPEndPoint([Net.IPAddress]::Any, 0)
[Text.Encoding]::UTF8.GetString($u.Receive([ref]$ep))
```
