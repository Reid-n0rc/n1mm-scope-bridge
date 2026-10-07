# Getting started

From a new install to your radio's waterfall in N1MM Logger+ (N1MM+), in
order. Each step links to the detailed page if you need more. Do steps 1–2
once; after that you only start the bridge.

## What you need

- A **supported Yaesu radio**: see [Pick your radio](radios/README.md). Today
  that is the FT-710; other Yaesu models are planned.
- The radio connected to the PC with its **USB cable**. No other cable or
  adapter.
- A PC with **Windows 10 or 11** that runs N1MM+.
- **N1MM+ already set up for the radio.** The bridge doesn't change that
  setup and never uses the radio's COM ports.

## 1. Set up the radio

Open your radio's page and do everything on it once. Each page gives the menu
path, the menu number and the button presses for every setting.

- [Yaesu FT-710](radios/ft-710.md): turn **SCU-LAN10** **ON**, set the scope
  to **CENTER**, then power-cycle the radio and replug the USB cable.

Other radios: [Pick your radio](radios/README.md).

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
   radio's scope to Center (see your radio's page). The window also offers
   N1MM+ function-key macros that do it for you.

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

- **`Could not open 'FT4222 A'`**: the radio's scope output is off (FT-710:
  SCU-LAN10), or the radio needs the power cycle **and** USB replug from its
  page in step 1. Close wfview if it is running.
- **Streaming, but nothing in N1MM+**: recheck the source name in step 4.
- Anything else: [Troubleshooting](troubleshooting.md) lists every message.
  Press **Copy diagnostics** in the window when asking for help.

N1MM Scope Bridge is an independent project, not affiliated with or endorsed
by the N1MM Logger+ project or N1MM. The N1MM+ steps follow N1MM+'s public
documentation.
