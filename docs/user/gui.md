# GUI

The window is the normal way to run the bridge. Start it from the **N1MM
Scope Bridge** shortcut (once the installer ships, #20) or with
`n1mm-scope-bridge-gui`. The window opens when the program starts, and your
settings are saved automatically as you change them (see [settings](settings.md)).

The window follows Windows' light or dark mode, uses the native Windows 11
look with your accent colour, and resizes (it opens at 960 × 640).

Screenshots of the window and its dialogs are on the website's
[Using the window](https://reid-n0rc.github.io/n1mm-scope-bridge/use.html) page.
They are taken automatically from the program itself
(`n1mm-scope-bridge gui --screenshot DIR`, see [`gui`](cli/gui.md)), so they
match the version they describe. Every streaming screenshot states where its
data came from: the main streaming window is a **real Yaesu FT-710** capture
(`--source radio`), labelled "Real radio" with the band, frequency, and date.
The home page shows a **live recording** of the window streaming real FT-710
data (`gui --record`, played back from a capture of the radio); visitors who
prefer reduced motion see a still image instead. Any screenshot generated from the built-in FT-710 emulator is labelled as
**simulated signals, not a real radio**.

## The window

The window is a dashboard of what the bridge is sending to N1MM+, from top to
bottom:

1. **Header.** The program name, with your radio and N1MM+ source name under
   it (for example *Yaesu FT-710 (USB) → N1MM+ as "FT-710"*). On the right:
   - the **status pill**: **Stopped** (grey), **Streaming** (green), or
     **Error** (red);
   - **Start** / **Stop**;
   - the **gear**, which opens [Settings](#settings);
   - the **⋯** menu: **Settings…**, **Copy diagnostics**, **N1MM+ setup
     guide**, and **About and license**.
2. **Preview.** A live spectrum line over a waterfall, showing exactly what
   N1MM+ receives. The bottom axis gives the low, centre, and high
   frequencies, and the left axis the level in dB. The level scale adapts to
   the strongest recent signal. Before you press Start it says *Press Start to
   stream your Yaesu scope to N1MM+* and points to the emulator.
3. **Cards**, updated several times a second:

   | Card | Shows |
   |---|---|
   | Frequency | The VFO-A frequency, for example **14.074 000 MHz** |
   | Span | The scope span and the frequency range it covers |
   | Scope mode | The radio's scope mode. **✓ Exact frequencies** (green) in Center mode; **Switch the radio to Center** (amber) otherwise, because N1MM+'s frequencies are only exact in Center mode |
   | To N1MM+ | Updates per second, and the N1MM+ PC and port |
   | Health | **OK**, **Degraded** (frames dropped or failing checks), or **Problem** (red, with the error) |

4. **Message line.** What is happening, for example *Streaming to N1MM+ at
   127.0.0.1:13064 as 'FT-710'*, or what to fix.
5. **Activity**, collapsed by default and showing the latest message. Click
   **Activity** to open the log of the last 500 messages (starts, stops,
   warnings, and errors).

**Copy diagnostics** (in the Activity bar and the ⋯ menu) copies the version,
your settings, the status, and the last 50 log lines to the clipboard, ready
to paste into a bug report. Your Windows account name is replaced with `~` in
any folder path.

The tray icon's tooltip shows a one-line summary, for example *Streaming
FT-710 to N1MM+, 4.0 per second*.

If streaming stops because of a problem, the pill shows **Error** and a
message explains what to do (see [troubleshooting](troubleshooting.md)). When
FTDI's library is missing, the message has an **Open FTDI download page**
button.

If the radio's scope can't be opened (`Could not open 'FT4222 A'`), the
message reminds you that the FT-710 needs **OPERATION SETTING → GENERAL →
SCU-LAN10** set to **ON**. See [Setting up your Yaesu radio](radio-setup.md).

## Start and Stop

Press **Start**. The pill turns green (**Streaming**), the button becomes
**Stop**, and the preview and cards come alive. If a setting is invalid,
Start opens Settings at the page with the problem, and the message line says
*Fix the highlighted settings, then press Start.*

## Settings

The gear (or **⋯ → Settings…**) opens Settings. Pages are listed on the left,
and **changes are saved automatically**. While streaming, the Radio, N1MM+,
Display, and Advanced pages are read-only (they apply on the next Start);
Startup and closing stays editable.

**Radio**

| Control | Setting | What it does |
|---|---|---|
| Radio | `radio` | The radio model, for example *Yaesu FT-710* |
| Use the built-in emulator (no radio needed) | `emulator` | Streams a simulated FT-710, so you can try the bridge or set up N1MM+ without the radio |
| FTDI library folder | `ftdi_lib_dir` | The folder with FTDI's `LibFT4222-64.dll` and `ftd2xx.dll`. Leave it empty to search the system path. **Browse…** picks a folder |

**N1MM+**

| Control | Setting | What it does |
|---|---|---|
| Source name | `source_name` | The name you pick in N1MM+'s Spectrum Display settings (shown greyed when it is the radio model) |
| N1MM+ PC | `n1mm_host` | `127.0.0.1` when N1MM+ runs on this PC |
| Port | `n1mm_port` | N1MM+'s spectrum port, normally 13064 |

**Display**

| Control | Setting | What it does |
|---|---|---|
| Updates | `rate_hz` | A slider for updates per second sent to N1MM+, from 0.5 to 10 in steps of 0.5 |
| Smoothing | `combine` | **Off** sends each frame as is, **Average** smooths noise, **Peak hold** keeps short signals |

**Startup and closing**

| Control | Setting | What it does |
|---|---|---|
| Start streaming when the program opens | `start_streaming_on_launch` | Presses Start for you at launch |
| Start hidden in the system tray | `start_minimized` | Opens straight to the tray icon, without the window |
| Close button | `on_close` | **Ask me**, **Keep running in tray**, or **Exit** |

**Advanced** (rarely needed)

| Control | Setting | What it does |
|---|---|---|
| Scaling | `scaling` | dB per level step that N1MM+ uses |
| FT4222 device | `device` | The FT4222 device description, normally `FT4222 A` |

A problem with a value is shown right under the field, for example
"⚠ port must be 1-65535 (N1MM+ uses 13064)".

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
setting, so you aren't asked again. Change it any time in **Settings →
Startup and closing**. **Exit** stops streaming, so N1MM+'s spectrum stops.

On a system with no tray (rare), Close exits and Minimize minimizes normally.

## Command-line options

| Option | Meaning |
|---|---|
| `--settings PATH` | Use a different settings file |
| `--self-test` | Open the window, stream the emulator to a local test listener, and exit with code 0 on success (used by CI and the release regression) |
| `--version` | Print the version |

