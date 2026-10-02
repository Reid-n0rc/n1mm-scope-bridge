# `probe`: check the setup

```
n1mm-scope-bridge probe [--radio MODEL] [--ftdi-lib-dir DIR] [--device TEXT] [--emulator] [--scenario NAME]
```

Loads the FTDI libraries, opens the radio, reads one frame, and prints the
VFO, span, and scope mode. Run this first if anything doesn't work.

```
FTDI libraries loaded.
FT-710 found on 'FT4222 A'.
VFO-A 14074000 Hz, span 20000 Hz, scope mode Center (Normal)
```

Options `--radio`, `--ftdi-lib-dir`, `--device`, `--emulator`, and `--scenario` work as for [`run`](run.md).
