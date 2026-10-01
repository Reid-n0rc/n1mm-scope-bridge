# GUI

The window is the normal way to run the bridge. Start it from the **N1MM
Scope Bridge** shortcut (once the installer ships, #20) or with
`n1mm-scope-bridge-gui`. The window opens when the program starts, and your
settings are saved automatically as you change them (see [settings](settings.md)).

The window follows Windows' light or dark mode and uses the native Windows 11
look.

## The window

**Radio**

| Control | Setting | What it does |
|---|---|---|
| Radio | `radio` | The radio model |
| Use the built-in emulator (no radio needed) | `emulator` | Streams a simulated FT-710, so you can try the bridge or set up N1MM+ without the radio |
| FTDI library folder | `ftdi_lib_dir` | The folder with FTDI's `LibFT4222-64.dll` and `ftd2xx.dll`. Leave it empty to search the system path. **Browse…** picks a folder |

**N1MM Logger+**

| Control | Setting | What it does |
|---|---|---|
| Source name | `source_name` | The name you pick in N1MM+'s Spectrum Display settings (shown greyed when it is the radio model) |
| N1MM+ PC | `n1mm_host` | `127.0.0.1` when N1MM+ runs on this PC |
| Port | `n1mm_port` | N1MM+'s spectrum port, normally 13064 |
| Updates | `rate_hz` | Updates per second sent to N1MM+ (at most 10) |
| Display | `combine` | **Latest**, **Average (smoother)**, or **Peak hold** |
| Scaling | `scaling` | dB per level step |

A problem with a value is shown right under the field, for example
"⚠ port must be 1-65535 (N1MM+ uses 13064)".

## Start and Stop

Press **Start**. The status chip at the top right changes to **Streaming**,
the settings lock until you press **Stop**, and the lines under the settings
show what the radio's scope is showing:

```
VFO 14.074000 MHz · span 20 kHz · Center (Normal)
Sent 120 · dropped 0 · bad 0
```

If the scope isn't in Center mode, the status line says so: set the radio's
scope to **Center** for exact frequencies in N1MM+.

If streaming stops because of a problem, the chip shows **Error** and a
message explains what to do (see [troubleshooting](troubleshooting.md)). When
FTDI's library is missing, the message has an **Open FTDI download page**
button.

**N1MM+ setup guide** opens the [N1MM+ setup instructions](../n1mm-setup.md).

**Startup and closing**

| Control | Setting | What it does |
|---|---|---|
| Start streaming when the program opens | `start_streaming_on_launch` | Presses Start for you at launch |
| Start hidden in the system tray | `start_minimized` | Opens straight to the tray icon, without the window |
| Close button | `on_close` | **Ask me**, **Keep running in tray**, or **Exit** |

These stay editable while streaming.

## Closing, minimizing, and the system tray

The bridge keeps a **system tray icon** (near the clock) while it runs. Its
tooltip shows **Streaming** or **Stopped**. Right-click it for:

- **Show window**: brings the window back (or double-click the icon)
- **Start streaming** / **Stop streaming**
- **Exit**: stops streaming and closes the program

**Minimize** hides the window to the tray. **Streaming continues**, so
N1MM+ keeps its spectrum. The first time each session, a notification says
the program is still running in the tray.

**Close (X)** asks:

> Keep streaming in the system tray, or exit N1MM Scope Bridge?
> **[Keep running in tray] [Exit] [Cancel]** and ☐ **Remember my choice**

Ticking **Remember my choice** saves your answer as the **Close button**
setting, so you aren't asked again. Change it any time in **Startup and
closing**. **Exit** stops streaming, so N1MM+'s spectrum stops.

On a system with no tray (rare), Close exits and Minimize minimizes normally.

## Command-line options

| Option | Meaning |
|---|---|
| `--settings PATH` | Use a different settings file |
| `--self-test` | Open the window, stream the emulator to a local test listener, and exit with code 0 on success (used by CI and the release regression) |
| `--version` | Print the version |
