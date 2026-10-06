# Getting started

From a new install to your radio's waterfall in N1MM Logger+ (N1MM+), in
order. Each step links to the detailed page if you need more. Do steps 1–2
once per radio; after that you only start the bridge.

## What you need

- A **Yaesu FT-710** (other Yaesu models are planned).
- The **USB cable** N1MM+ already uses for CAT. No other cable or adapter.
- A PC with **Windows 10 or 11** that runs N1MM+.
- **N1MM+ already controlling the radio** (CAT working). If it isn't yet, set
  that up first: see N1MM+'s [Configurer](https://n1mmwp.hamdocs.com/setup/the-configurer/)
  (Hardware tab) and its notes for the
  [FT-710](https://n1mmwp.hamdocs.com/manual-supported/supported-radios/#ft-710).

## 1. Set up the radio

These FT-710 settings are needed. The first two are what this bridge needs;
the CAT settings are N1MM+'s own recommendations, listed here so everything
is in one place.

| Setting | Where | Set to | Why |
|---|---|---|---|
| SCU-LAN10 | **OPERATION SETTING → GENERAL → SCU-LAN10** (CAT menu **EX 03-01-26**) | **ON** | Makes the radio send its scope over USB. You do **not** need the SCU-LAN10 adapter. With it OFF the bridge reports `Could not open 'FT4222 A'`. |
| Scope mode | The radio's scope | **Center** | N1MM+'s frequencies are exact only in Center mode. In Cursor or Fixed mode the bridge still works but warns. |
| CAT-1 RATE | Radio menu | Same as N1MM+'s port speed (N1MM+ suggests **38400**) | N1MM+'s recommendation for the FT-710 |
| CAT-1 Time Out Timer | Radio menu | **1000** or higher | N1MM+'s recommendation for the FT-710 |

N1MM+'s FT-710 notes also set the CAT-1 ("Enhanced") COM port in N1MM+ to
38400, N, 8, 1, with DTR and RTS **Always Off**. The bridge never uses either
COM port, so N1MM+ keeps both.

After turning SCU-LAN10 on:

1. Turn the radio **off and back on**.
2. **Unplug the USB cable and plug it back in.** A power cycle alone is not
   enough; the scope device only appears after the cable is replugged.

Details: [Setting up your Yaesu radio](radio-setup.md).

## 2. Install the bridge

1. Download `n1mm-scope-bridge-setup-<version>.exe` from the
   [latest release](https://github.com/Reid-n0rc/n1mm-scope-bridge/releases/latest).
   One installer covers 64-bit, ARM and 32-bit Windows PCs.
2. Run it. It installs for your Windows account only, with no administrator
   prompt.
3. Leave **Download FTDI's LibFT4222 library** ticked (the default). The FT-710
   sends its scope through an FTDI FT4222 chip, and this library reads it.
   Setup downloads FTDI's signed files and checks them.
4. If setup offers **Install FTDI USB driver (needs administrator)**, Windows
   doesn't have FTDI's driver yet: tick it (or let Windows Update install it
   when you plug in the radio).
5. The installer isn't code-signed yet, so Windows SmartScreen may warn:
   choose **More info → Run anyway**.

Details: the [install page](https://reid-n0rc.github.io/n1mm-scope-bridge/install.html)
(which PC gets which version, Windows on ARM, installing without internet).

## 3. Start the bridge

1. Start **N1MM Scope Bridge** from the Start menu. On 32-bit Windows, use
   **N1MM Scope Bridge (command line)**.
2. Press **Start**. The status pill turns green (**Streaming**) and the cards
   show your radio's frequency, span and scope mode.
3. If the **Scope mode** card says **Switch the radio to Center**, set the
   radio's scope to Center. The window offers N1MM+ function-key macros that
   do it for you.

No radio handy? Turn on **Use the built-in emulator** to try everything
first. Details: [GUI](gui.md).

## 4. Show it in N1MM+

Start the bridge first, so N1MM+ can see its source name.

1. In N1MM+, open **Window → Spectrum Display**.
2. Click the **gear** icon. In the **Spectrum Source** pane choose **For all
   other radios, source named**, then pick the bridge's name in **External
   Source Name**. By default the name is the radio model, `FT-710`.
3. For SO2R, choose **Radio 1** or **Radio 2** in **General Options** to match
   the radio the bridge is reading.

That's all: the bridge sends the frequency range and level scaling with
every update, so there is nothing else to set. N1MM+ runs on a different PC?
See [Setting up N1MM Logger+](../n1mm-setup.md#running-n1mm-on-another-pc).

N1MM+'s own documentation:
[The Spectrum Display Window](https://n1mmwp.hamdocs.com/manual-windows/spectrum-display-window/).

## 5. Check it works

- The bridge's status pill says **Streaming** and **Health** says **OK**.
- N1MM+'s Spectrum Display shows the waterfall, and its frequency scale
  matches the radio's VFO.

No waterfall?

- **`Could not open 'FT4222 A'`**: SCU-LAN10 is OFF, or the radio needs the
  power cycle **and** USB replug from step 1. Close wfview if it is running.
- **Streaming, but nothing in N1MM+**: recheck the source name in step 4.
- Anything else: [Troubleshooting](troubleshooting.md) lists every message.
  Press **Copy diagnostics** in the window when asking for help.

N1MM Scope Bridge is an independent project, not affiliated with or endorsed
by the N1MM Logger+ project or N1MM. The N1MM+ steps follow N1MM+'s public
documentation.
