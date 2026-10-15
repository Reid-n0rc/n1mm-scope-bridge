# Pick your radio

Set up your radio once, before the first time you start the bridge. Each
radio has its own page with every setting the bridge needs: the menu path, the
menu number, and the button presses.

| Radio | Setup page | Status |
|---|---|---|
| Yaesu FT-710 | [FT-710 setup](ft-710.md) | Supported |

The FTDX10 is planned. Own one and can help test? Open a **Radio support
request**:
<https://github.com/Reid-n0rc/n1mm-scope-bridge/issues/new/choose>.

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
