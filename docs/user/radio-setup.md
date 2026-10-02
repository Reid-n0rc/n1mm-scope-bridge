# Setting up your Yaesu radio

Do this once per radio, before the first time you start the bridge.

## Yaesu FT-710

1. **Connect the radio to the PC with a USB cable**: the same cable N1MM+
   already uses for CAT. No other cable or adapter is needed.
2. **Turn on the scope output:** on the radio, open the menu
   **OPERATION SETTING → GENERAL → SCU-LAN10** and set it to **ON**.
   - You do **not** need the SCU-LAN10 network adapter. This menu item is what
     makes the radio send its spectrum scope over USB (through an FTDI FT4222
     chip inside the radio).
   - With it **OFF**, the scope interface doesn't appear on the PC at all, and
     the bridge reports `Could not open 'FT4222 A'`.
   - ON is the factory default, but it is often switched off.
   - In Yaesu's CAT manual this is menu **EX 03-01-26** (`0` OFF, `1` ON).
3. **FTDI's LibFT4222 library** reads that FT4222 chip. The Windows installer
   downloads it for you: the **Download FTDI's LibFT4222 library** option is on
   by default, and setup checks FTDI's signed files before putting them in the
   program folder. (Its licence doesn't let us ship it inside this GPL
   program.) If you installed without it, run setup again with the option
   ticked, or get LibFT4222 from <https://ftdichip.com/products/ft4222h/> and
   set **FTDI library folder** in Settings. The USB driver itself normally
   comes from Windows Update automatically.
4. **Make the PC see the new scope device.** After turning SCU-LAN10 on:
   1. Turn the radio **off and back on**.
   2. **Unplug the USB cable and plug it back in.** A power cycle alone is not
      enough; on the maintainer's FT-710 the scope device only appeared after
      the cable was replugged.
   3. Check that the scope device appears: run `n1mm-scope-bridge probe`, or
      press **Start** in the window. (It shows up as an FTDI **FT4222** USB
      device, VID `0x0403`, PID `0x601C`.)
5. **Set the scope to Center mode** for exact frequencies in N1MM+. In Cursor
   or Fixed mode the bridge still streams, but it warns that the frequency
   edges are approximate. It can give you ready-to-paste N1MM+ function-key
   macros to switch the scope to Center and back.
6. **Leave N1MM+ connected as usual.** N1MM+ keeps both of the radio's COM
   ports (CAT and the PTT/keying port). The bridge reads the scope through the
   separate FT4222 device and never opens either COM port.

### What the bridge never does

- It never transmits or keys the radio.
- It never opens the radio's COM ports, so it can't change radio settings
  through CAT.
- It never changes the SCU-LAN10 setting; you set that once on the radio.

To turn the scope output off again, set **SCU-LAN10** back to **OFF**.

## Other Yaesu radios

The FTDX10, the FTDX101D/MP, and radios on the SCU-LAN10 network adapter are
planned. Setup steps will be added here when each radio is supported.

See also: [Setting up N1MM Logger+](../n1mm-setup.md) and
[Troubleshooting](troubleshooting.md).
