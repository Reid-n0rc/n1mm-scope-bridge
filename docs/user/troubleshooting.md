# Troubleshooting

When asking for help, press **Copy diagnostics** in the window's Log section
and paste the result into your report.

Run `n1mm-scope-bridge probe` first. It checks the FTDI library and the radio
connection in one step. Every error the program can show is listed below.

| Message (start of) | Cause | Fix |
|---|---|---|
| `Could not load FTDI's LibFT4222/D2XX libraries` (the message says which DLL is `missing:`) | FTDI's LibFT4222 (and ftd2xx) DLLs aren't installed or aren't on the search path (for example setup's FTDI download was unticked or had no internet) | Run setup again with **Download FTDI's LibFT4222 library** ticked, or install LibFT4222 from <https://ftdichip.com/products/ft4222h/> and point **FTDI library folder** / `--ftdi-lib-dir` at the folder with `LibFT4222-64.dll` and `ftd2xx.dll` |
| `FTDI library folder does not exist` | The configured FTDI folder is wrong | Fix the folder in Settings or `--ftdi-lib-dir` |
| `Found FTDI DLLs built for ARM64 … but this app runs as x64` | The chosen folder holds DLLs for a different processor (for example `dll\arm64` for the x64 app). The installer's default app on Windows on ARM is x64; the native ARM64 app needs `arm64` DLLs and the 32-bit app `i386` ones | Pick the unzipped FTDI package folder itself (for example `LibFT4222-v1.4.8`) and the DLLs for this app are found automatically, or reinstall the x64 (or 32-bit) version and let the installer download them |
| `FTDI library is missing a required function` | An old or wrong DLL was found | Install the current LibFT4222 from FTDI and remove old copies |
| `Could not open 'FT4222 A'` | FT-710 menu **OPERATION SETTING → GENERAL → SCU-LAN10** is OFF (the scope interface then doesn't exist on USB), radio off, USB cable unplugged, the FTDI D2XX driver missing, or another program (for example wfview) already has the scope open | On the FT-710 set **SCU-LAN10** to **ON** (no adapter needed), then turn the radio off and on **and** unplug and replug the USB cable (a power cycle alone isn't enough). Check the driver, close wfview, and run `probe` |
| `… failed (FT_IO_ERROR)` | USB communication failed during setup or reading | Reconnect the USB cable (avoid unpowered hubs) and try again |
| `No valid scope frames from 'FT4222 A'` | The radio is connected but isn't sending scope data | Make sure the radio's scope display is on, power-cycle the radio, then try again |
| `scope is in … mode; frequency edges are only exact in Center mode` | The radio's scope is in Cursor or Fixed mode | Set the FT-710's scope to **Center** mode for an accurate N1MM+ display |
| `The window needs PySide6, which is not installed` | `n1mm-scope-bridge gui` was run from a pip install without the GUI package | Use the Windows installer, or `pip install "n1mm-scope-bridge[gui]"` |
| `unknown radio` | The `--radio` value or `radio` setting isn't supported | Run `list-radios` |
| `was recorded from a … not a …` | The replayed capture came from a different radio model | Use `--radio` matching the capture |
| `not an n1mm-scope-bridge capture` | The file given to `--replay` isn't a capture | Record one with `record` |
| `trailing partial frame` | The capture file was cut short | Record it again |
| `not an n1mm-scope-bridge raw stream capture`, `truncated raw record header`, `truncated raw chunk`, `raw chunk of … bytes exceeds` | A `record --raw-stream` file is damaged, cut short, or isn't a raw capture | Record it again with `record --raw-stream`; raw captures are only for checking the emulator against a radio |
| `capture has no frames to loop` | `--loop` with an empty capture | Record a capture with at least one frame |
| `unsupported capture format`, `capture model name … must be`, `frame size must be in` | The capture's header is from a newer version or is damaged | Record it again with this version |
| `capture frame is … bytes, expected …` | Internal check while recording; the radio returned a frame of the wrong size | Open an issue with the command you ran |
| `replay fps must be >= 0` | `--fps` is negative | Use a positive number, for example 20 |
| `Could not start remote control on` | Another program (or a second bridge) already uses the remote-control port | Close the other program or choose another `control_port` / `--control-port` |
| `No reply from n1mm-scope-bridge at` | `ctl` found no running bridge with remote control enabled at that address | Start the bridge with remote control on (`run --control-port 13070` or the GUI setting) and check `--host`/`--port` |
| `control port must`, `control address must`, `a non-loopback control address needs` | Invalid remote-control settings, including `control_bind` set to all interfaces (`0.0.0.0` or `::`), which is never allowed | Correct the named setting; see [UDP remote control](udp-control.md) |
| `--frames must be at least 1` | `record --frames 0` | Use 1 or more |
| `--name must not be empty` | `--name ""` | Give a name, or leave `--name` out to use the radio model |
| `n1mm_port: port must be 1-65535` (and other `setting: problem` messages) | An invalid setting or option | Correct the named setting; see [settings](settings.md) |

## Center scope mode

`Set the FT-710's scope to Center mode` means the scope is in Cursor or Fixed
mode, so N1MM+'s frequency scale is approximate. Switch the radio's scope to
**Center** on the front panel (or with your own N1MM+ macro, for example
`{CAT1ASC SS0640000;}`, which N1MM+ sends over its CAT port). The bridge
confirms when it sees Center. It never changes the mode itself and never
opens the radio's COM ports.

## N1MM+ shows no spectrum

1. In N1MM+, open **Window → Spectrum Display**, click the gear, choose
   **For all other radios, source named**, and pick the bridge's name (by
   default `FT-710`). Start the bridge first so the name is listed.
2. If N1MM+ runs on another PC, use `--host` with that PC's address and allow
   UDP port 13064 through its firewall.
3. The bridge's status line should show `sent` increasing. If `read`
   increases but `bad` does too, record a short capture and open an issue.
