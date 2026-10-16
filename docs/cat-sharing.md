# Design note: CAT sharing through a virtual COM port (#98)

Status: **research only. Recommendation: no-go for now** (see
[Recommendation](#recommendation)). Nothing here is implemented or
scheduled. Researched 2026-10-15.

> **This mode conflicts with AGENTS.md rule 8.** Today the bridge never
> transmits, never keys the radio, and never opens a COM port. CAT sharing
> means the bridge opens the FT-710's CAT (Enhanced) port and relays every
> N1MM Logger+ (N1MM+) command, including commands that transmit. It could
> only ever ship as an **opt-in, off-by-default** mode, and only after the
> maintainer revisits rule 8 and `tests/test_no_com_ports.py` in a
> separate, approved issue. The **Standard** port (PTT, CW and FSK keying) is
> **never** proxied under any design in this note. It stays connected
> directly to N1MM+.

## Goal

The bridge would own the FT-710's real CAT-1 (Enhanced) port and present a
virtual COM port to N1MM+, forwarding traffic both ways. That would let the
bridge set and restore the scope mode itself (#62, `SS06`) and cross-check
the frequency it decodes from the scope frame. #62 already shipped without
CAT: the bridge confirms Center mode from the scope frame and the operator
can use N1MM+ macros (`{CAT1ASC SS0640000;}`), see
[design/scope-center-mode.md](design/scope-center-mode.md).

```text
N1MM+ ── COMx (virtual) ═ com0com pair ═ COMy (virtual) ── bridge ── COM5 (FT-710 Enhanced, CAT-1)
N1MM+ ── COM6 (FT-710 Standard, CAT-2: PTT/CW/FSK) ............ direct, never proxied
```

## 1. Virtual COM port drivers on Windows 10/11

Windows needs a kernel-mode driver to create a COM port pair. Since Windows
10 version 1607, Windows with Secure Boot on loads a new kernel-mode driver
only if Microsoft signed it through the Hardware Dev Center (attestation or
WHCP/HLK); cross-signed drivers load only under narrow exceptions, such as
Secure Boot off ([Microsoft, Driver Signing Policy][ms-policy]). From the
April 2026 update, Windows 11 24H2, 25H2 and 26H1 and Windows Server 2025
also stop trusting the old cross-signed program, apart from a small allow
list ([Microsoft Windows IT Pro blog][ms-xsign], [OSnews][osnews]). Test
signing (`bcdedit -set TESTSIGNING ON`) weakens security and is not
acceptable for operators.

| Driver | Signing today | ARM64 | License and redistribution |
|---|---|---|---|
| com0com 3.0.0.0 | Microsoft Update Catalog lists six Vyacheslav Frolov 3.0.0.0 packages (Ports, CNCPorts) for "Windows 10 and later drivers", dated 2015-10-09 ([catalog][catalog]); SourceForge has a `-signed.zip` from 2017 and a test-signed build ([files][c0c-files]). Other "signed" builds circulate from third parties ([BrickBot archive][brickbot]). UNVERIFIED: whether the 2017 zip is the Microsoft-signed build, and whether it loads with Memory Integrity (HVCI) on | None | GPL-2.0-or-later ([source header and `license.txt`][c0c-src]); compatible with our GPL-3.0-only. No upstream release since 2012 (source) and 2017 (signed zip) |
| hub4com, com2tcp | User-mode tools from the com0com project, no driver of their own ([com0com][c0c]) | n/a | GPL. hub4com merges streams byte by byte, so it can't keep `;` commands whole: not suitable as the arbiter |
| VSPE (Eterlogic) | Current kernel driver signed; supports Windows 11 x64 and ARM64 (from 1.1.6.760) ([VSPE][vspe]) | Yes | Proprietary; a license is required on 64-bit Windows. Not redistributable in a GPL installer |
| Virtual Serial Ports (HHD) | "All drivers are digitally signed"; x86, x64, ARM64 ([HHD][hhd]) | Yes | Shareware, from USD 89.99. Not redistributable |
| Virtual Serial Port Driver (Eltima) | Microsoft-signed drivers, ARM64 support in 11.x ([release notes][eltima]) | Yes | Commercial. Not redistributable |

Ham operators report mixed results with com0com on Windows 11 (one blocked
by driver signing, another running eight pairs without trouble) and good
results with VSPE ([eSDR forum][eesdr]). Hamlib's `rigctlcom`, which does a
similar job for TS-2000 emulation, names com0com, Free Virtual Serial Ports
and VSPD as the Windows options ([rigctlcom(1)][rigctlcom]).

### What installing com0com from our Inno Setup installer implies

- **Admin and UAC.** Our installer runs with `PrivilegesRequired=lowest`
  (`packaging/windows/installer.iss`). A driver install needs elevation, so
  the CAT-sharing component would force a UAC prompt (or a separate elevated
  helper) for everyone who ticks it.
- **Signing.** We can't re-sign com0com ourselves: a kernel signature needs
  an EV certificate and a Hardware Dev Center account, and SignPath (#130)
  signs only our own build outputs ([code-signing-policy.md](code-signing-policy.md)).
  We would depend on Frolov's 2015 Microsoft-signed packages for as long as
  Windows keeps loading them.
- **ARM64.** Our installer has an ARM64 build. com0com has none, so the mode
  would be unavailable there.
- **Secure Boot.** Fine with a Microsoft-signed package; impossible with the
  test-signed build unless the operator turns off Secure Boot. We never ask
  operators to do that.
- **Uninstall.** com0com ships its own uninstaller (`uninstall.exe /S`) and
  `setupc` for creating and removing pairs ([com0com ReadMe][c0c-src]). Our
  uninstaller would have to remove the pairs and the driver package, and must
  not remove a com0com that another program (for example an SDR or CW
  skimmer) installed first.
- **Antivirus and SmartScreen.** Our installer is not code-signed yet, so
  SmartScreen already warns. Adding a kernel driver raises the bar: some
  antivirus products flag installers that drop drivers. UNVERIFIED: needs a
  check on a clean Windows 11 VM with Defender and Smart App Control.
- **Distribution.** Like the FTDI libraries (rule 7, #133), the installer
  should download a pinned, SHA-256 and Authenticode-checked package at
  install time rather than bundle it. Bundling is allowed by GPL-2.0-or-later
  but then the release must also carry or offer com0com's exact source.

## 2. Forwarding design for Yaesu CAT

Facts from Yaesu's FT-710 CAT Operation Reference Manual (Japanese edition,
distributed by Exseli, pp. 1–7) ([Yaesu][yaesu-cat]):

- The radio has two USB virtual COM ports: **Enhanced (CAT-1)** for CAT, and
  **Standard (CAT-2)** for TX control (PTT, CW keying, FSK). The manual
  warns that RTS/DTR on CAT-2 can put the radio into transmit.
- CAT-1 defaults to 38400 bps, 8 data bits, no parity, 1 stop bit. Menu
  **OPERATION SETTING → GENERAL → CAT-1 TIME OUT TIMER** offers 10, 100,
  1000 or 3000 ms (default 10 ms).
- A command is two letters (either case), parameters, and a mandatory `;`.
  There are Set, Read and Answer forms. A Set has **no** answer.
- On a malformed command, or one the radio can't execute now, the radio
  sends `?;`.
- `AI1;` turns on auto information: the radio sends the Answer of every
  AI-capable command when its state changes (`FA`, `MD`, `SS` and others).
  AI is set **per port** (CAT-1, CAT-2, CAT-3) and turns off at power-off.
- The command list includes commands that transmit or key: `TX`, `MX`
  (MOX), `KY` (CW keying), `AC` (tuner start), `PB` (voice playback).

N1MM+ facts ([N1MM+ Supported Radios][n1mm-radios]): use the Enhanced port
for radio control and the Standard port for CW/FSK/PTT; set CAT-1 to 38400,
N, 8, 1 with RTS and DTR always off; set **CAT-1 TIME OUT TIMER** to 1000 ms
or more. N1MM+ does not document its FT-710 polling commands, rate, or
whether it enables AI. UNVERIFIED (#5): capture N1MM+'s CAT-1 traffic on the
bench before any design is fixed.

### Proposed proxy behaviour (if ever built)

1. **Frame on `;`.** Split both directions into whole commands. Never
   interleave bytes of two commands. Forward N1MM+'s commands unchanged and
   in order; the bridge never rewrites, drops or delays them beyond the
   arbitration window below.
2. **Arbitrate.** The bridge's own commands go into a queue and are sent only
   when N1MM+ has no Read outstanding (its last Read was answered or timed
   out). N1MM+ commands that arrive meanwhile wait until the bridge's command
   finishes.
3. **Inject Sets only.** The bridge's whitelist is the scope commands it
   needs (`SS05…;` span and `SS06…;` mode), as in `scripts/dev_cat.py`. It
   reads state from the scope frame, not by CAT Read, so it never has to
   route an Answer to itself. A `TX`, `MX`, `KY`, `AC`, `PS` or any
   non-whitelisted command from the bridge is a bug and is refused before it
   reaches the port.
4. **Quiet window.** A Set has no answer, so after each injected Set the
   proxy waits a short window (proposed 30 ms) for a possible `?;`. A `?;` in
   that window is the bridge's and is not forwarded; otherwise it goes to
   N1MM+. UNVERIFIED (#5): the radio's real `?;` latency.
5. **AI.** Forward AI Answers to N1MM+ unchanged. If N1MM+ enabled AI,
   N1MM+ also sees the `SS…;` Answer caused by the bridge's Set. UNVERIFIED
   (#5): whether N1MM+ ignores an unexpected `SS` Answer. The bridge never
   sends `AI` itself.
6. **Timeouts.** A Read with no Answer within 200 ms (proposed) frees the
   arbiter. The proxy keeps no other state, so a lost byte can't wedge it.
7. **Port settings.** Open the real port with RTS and DTR held low before
   anything is written, matching N1MM+'s "Always Off" advice and
   `scripts/dev_cat.py`.

### Latency budget for a band change

| Step | Budget |
|---|---|
| Wire time of `FA014074000;` at 38400 bps (12 bytes, 10 bits each) | about 3 ms, unchanged by the proxy |
| com0com pair, kernel to user and back | under 1 ms (UNVERIFIED) |
| Proxy read, frame and write, per direction | 5 ms target, 10 ms ceiling |
| Waiting behind one injected Set and its quiet window | 35 ms worst case, rare |
| **Added delay per N1MM+ command** | **≤ 10 ms typical, ≤ 50 ms worst case** |

An operator won't notice 50 ms on a band change. Repeated slips on every
poll during a run would show as a sluggish bandmap, so the on-air test
measures them.

## 3. Failure safety

The real risk is not latency but losing CAT mid-contest: with no CAT,
N1MM+ logs QSOs on a stale band or frequency. Keying is unaffected because
the Standard port stays direct.

- **Separate process.** The proxy runs as its own small process, not in the
  GUI or the scope pipeline, so a GUI or FT4222 fault can't stop CAT.
- **Watchdog.** The GUI supervises the proxy: if the process dies or stops
  forwarding for 2 s, restart it once; on a second failure, stop and show an
  error. N1MM+ keeps its virtual port open, so a quick restart is invisible
  to it.
- **Go direct.** A **Go direct** button stops the proxy and releases the
  real port, then tells the operator exactly what to change: in N1MM+,
  **Config → Configure Ports…**, set the radio to the real Enhanced port
  (shown by name), and press **OK**. The bridge must not edit N1MM+'s
  configuration files. The scope stream keeps running, because it uses the
  FT4222, not CAT.
- **Bridge crash mid-contest.** CAT stops until the watchdog restarts the
  proxy or the operator goes direct. The user docs must say so, and the
  N1MM+ setup page must keep the direct setup as the default.
- **Start and stop.** The proxy must be running before N1MM+ starts, and
  closing the bridge must not close the proxy while N1MM+ is running
  (system tray, #19).
- **Scope restore.** A crash can't restore the scope mode; the operator
  uses the existing prompt or macro.

## 4. Test plan

- **CI (no radio, no driver).** A CAT mock in the emulator answers `FA`,
  `IF`, `MD`, `SS` Reads, applies Sets, sends `?;` on bad input, and sends AI
  Answers when AI is on, with configurable delays. The proxy runs between two
  in-memory byte streams (fake "N1MM+" and the mock), so tests cover framing,
  arbitration, the whitelist, quiet windows, timeouts, and the watchdog with
  an injected clock and events, never sleeps.
- **Windows CI.** Installer tests (Pester) mock `setupc` and driver install;
  no driver is installed in CI.
- **Bench (hardware, opt-in).** Capture N1MM+'s CAT-1 traffic for a few
  minutes of normal use and a band change; measure `?;` latency and AI
  behaviour with a `hardware` test.
- **On-air (maintainer, #5).** N1MM+ through the proxy on a real FT-710 for a
  mock contest hour: band changes, CW and SSB QSOs keyed via the Standard
  port, scope Center set and restored, a forced proxy kill, and **Go
  direct**. Record firmware version and results in the issue.

## Recommendation

**No-go for now.** Revisit only if the maintainer wants it after on-air use
of the released bridge.

- **Driver risk.** The only free, GPL-compatible driver is com0com, whose
  Microsoft-signed packages date from 2015, with no ARM64 build and no active
  upstream. Windows driver policy keeps tightening (cross-signed trust removed
  in April 2026). The signed alternatives are proprietary and can't ship in
  our installer.
- **Safety.** It puts the bridge in N1MM+'s CAT path, including commands
  that transmit, which contradicts rule 8, and a crash leaves the logger
  without CAT mid-contest.
- **Small gain.** #62 already works without CAT (frame confirmation plus
  `{CAT1ASC …}` macros), and frequency comes from the scope frame.

Worth watching instead: N1MM+ adding a CAT passthrough to its UDP interface,
or a maintained, Microsoft-signed, GPL-compatible virtual port driver with
ARM64. The FT-710's **TUNER/LINEAR** jack can be set to **CAT-3** (5 V TTL,
menu **OPERATION SETTING → GENERAL → TUN/LIN PORT SELECT**) ([Yaesu][yaesu-cat]
p. 3). That is a third, separate CAT port that needs no proxy, but it needs a
TTL adapter, can't be used together with an external tuner or amplifier, and
also needs a rule 8 decision.

## Issue breakdown (only if the maintainer says go)

Each fits AGENTS.md task sizing (≤ 300 lines excluding tests, ≤ 5 files).

| # | Issue | Lane | Main files |
|---|---|---|---|
| 0 | Decide and amend rule 8 for opt-in CAT sharing; update `tests/test_no_com_ports.py` | `lane:process` | `AGENTS.md`, `tests/test_no_com_ports.py`, `docs/privacy.md` (no network use) |
| 1 | Bench capture of N1MM+ FT-710 CAT-1 traffic (polling, AI, `?;` latency); findings in the issue | `lane:core` | `scripts/` capture helper, issue comment |
| 2 | Pure Yaesu CAT framing and whitelist classifier | `lane:core` | `src/n1mm_scope_bridge/cat/framing.py`, tests |
| 3 | Emulator CAT mock (Reads, Sets, `?;`, AI, delays) | `lane:core` | `src/n1mm_scope_bridge/emulator/cat.py`, `docs/emulator.md`, tests |
| 4 | Pure arbiter: queue, quiet window, timeouts, injected clock | `lane:core` | `src/n1mm_scope_bridge/cat/arbiter.py`, tests |
| 5 | Windows serial adapter (stdlib `ctypes`, RTS/DTR low before open), behind a seam | `lane:core` | `src/n1mm_scope_bridge/transport/serial_win.py`, tests with a fake kernel32 |
| 6 | Proxy process and watchdog, `cat-proxy` CLI command | `lane:core` | `cat/proxy.py`, `cli/commands/cat_proxy.py`, `docs/user/cli/cat-proxy.md`, tests |
| 7 | Installer: optional, off-by-default com0com download (pin, SHA-256, signature), pair setup, safe uninstall, x64 only | `lane:packaging` | `packaging/windows/installer.iss`, `packaging/windows/com0com_pin.json`, a `.ps1` helper, Pester tests |
| 8 | GUI: CAT sharing settings page, status card, **Go direct** | `lane:gui` | `gui/settings_dialog.py`, `gui/cat_panel.py`, `docs/user/gui.md`, tests |
| 9 | User docs, troubleshooting messages, regression step | `lane:site` | `docs/user/n1mm-setup.md`, `docs/user/troubleshooting.md`, `scripts/regression_steps/NN_cat_proxy.py` |

Issue 0 blocks all others; issue 1 blocks 4 and 6.

## Sources

Facts about the FT-710 come only from Yaesu's manual; no code was copied
from any source.

[yaesu-cat]: https://exseli.com/pdf/uploaded/manual_trn_809495519.pdf
[n1mm-radios]: https://n1mmwp.hamdocs.com/setup/supported-radios/
[ms-policy]: https://learn.microsoft.com/en-us/windows-hardware/drivers/install/kernel-mode-code-signing-policy--windows-vista-and-later-
[ms-xsign]: https://techcommunity.microsoft.com/blog/windows-itpro-blog/advancing-windows-driver-security-removing-trust-for-the-cross-signed-driver-pro/4504818
[osnews]: https://www.osnews.com/story/144691/microsoft-removes-trust-for-drivers-signed-with-the-cross-signed-driver-program/
[catalog]: https://www.catalog.update.microsoft.com/Search.aspx?q=com0com
[c0c]: https://com0com.sourceforge.net/
[c0c-files]: https://sourceforge.net/projects/com0com/files/com0com/3.0.0.0/
[c0c-src]: https://github.com/tanvir-ahmed-m4/com0com
[brickbot]: https://github.com/BrickBot/Archive/releases
[vspe]: https://eterlogic.com/Products.VSPE.html
[hhd]: https://hhdsoftware.com/virtual-serial-ports
[eltima]: https://wiki.eltima.com/user-guides/vspd-guide/whats-new.html
[eesdr]: https://eesdr.com/en/forum-en/connection-to-third-party-software-esdr3/9977-what-is-the-recommended-virtual-serial-port-solution-for-windows-11
[rigctlcom]: https://man.archlinux.org/man/rigctlcom.1.en

- Yaesu, *FT-710 CAT Operation Reference Manual* (Japanese): <https://exseli.com/pdf/uploaded/manual_trn_809495519.pdf>
- N1MM+ manual, *Supported Radios*: <https://n1mmwp.hamdocs.com/setup/supported-radios/>
- Microsoft, *Driver Signing Policy*: <https://learn.microsoft.com/en-us/windows-hardware/drivers/install/kernel-mode-code-signing-policy--windows-vista-and-later->
- Microsoft Windows IT Pro blog, *Removing trust for the cross-signed driver program*: <https://techcommunity.microsoft.com/blog/windows-itpro-blog/advancing-windows-driver-security-removing-trust-for-the-cross-signed-driver-pro/4504818>
- OSnews summary (2026-03-27): <https://www.osnews.com/story/144691/microsoft-removes-trust-for-drivers-signed-with-the-cross-signed-driver-program/>
- Microsoft Update Catalog, com0com: <https://www.catalog.update.microsoft.com/Search.aspx?q=com0com>
- com0com project, downloads and source mirror: <https://com0com.sourceforge.net/>, <https://sourceforge.net/projects/com0com/files/com0com/3.0.0.0/>, <https://github.com/tanvir-ahmed-m4/com0com>
- Third-party signed com0com builds: <https://github.com/BrickBot/Archive/releases>
- VSPE: <https://eterlogic.com/Products.VSPE.html>; HHD Virtual Serial Ports: <https://hhdsoftware.com/virtual-serial-ports>; Eltima VSPD: <https://wiki.eltima.com/user-guides/vspd-guide/whats-new.html>
- eSDR forum, virtual serial ports on Windows 11: <https://eesdr.com/en/forum-en/connection-to-third-party-software-esdr3/9977-what-is-the-recommended-virtual-serial-port-solution-for-windows-11>
- Hamlib `rigctlcom(1)`: <https://man.archlinux.org/man/rigctlcom.1.en>
