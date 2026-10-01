# Setting up N1MM Logger+

> The bridge is pre-alpha. These steps describe the intended setup, and they
> will be confirmed during hardware validation.

1. Keep N1MM+ connected to the FT-710 for CAT as usual (Config → Configure
   Ports…). The bridge does not use the CAT COM port.
2. Start `n1mm-scope-bridge` first, so N1MM+ can see its source name. The
   default name is `FT-710` (`--name` changes it).
3. Open **Window → Spectrum Display**.
4. Click the **gear** icon. In the **Spectrum Source** pane, choose **For all
   other radios, source named**, then pick the bridge's name from the
   **External Source Name** list (or type it).
5. For SO2R, choose **Radio 1** or **Radio 2** in **General Options** to match
   the radio the bridge is reading.

The bridge sends the frequency edges and the dB scaling factor with every
packet, so N1MM+ needs no manual span or scaling setup.

## Running N1MM+ on another PC

N1MM+ listens on UDP 13064. Point the bridge at that PC with `--host <ip>`,
and allow inbound UDP 13064 in that PC's firewall.

## Source

N1MM+ manual, *The Spectrum Display Window*:
<https://n1mmwp.hamdocs.com/manual-windows/spectrum-display-window/>
