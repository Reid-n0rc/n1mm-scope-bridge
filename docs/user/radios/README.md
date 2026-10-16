# Supported radio

The bridge supports the Yaesu FT-710 only. Set it up once, before the first
time you start the bridge. Its page has every setting the bridge needs: the
menu path, the menu number, and the button presses.

| Radio | Setup page | Status |
|---|---|---|
| Yaesu FT-710 | [FT-710 setup](ft-710.md) | Supported |

## Leave N1MM+ connected as usual

N1MM+ keeps both of the radio's COM ports (CAT and the PTT/keying port). The
bridge reads the scope through a separate USB device and never opens either
COM port.

## What the bridge never does

- It never transmits or keys the radio.
- It never opens the radio's COM ports, so it can't change radio settings
  through CAT.
- It never changes the radio's menu settings; you set them once on the radio.

See also: [Getting started](../getting-started.md),
[Setting up N1MM Logger+](../../n1mm-setup.md) and
[Troubleshooting](../troubleshooting.md).
