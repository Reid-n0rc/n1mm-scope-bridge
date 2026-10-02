# Real-radio screenshots

Screenshots captured from a real radio (receive only) with:

```
n1mm-scope-bridge gui --screenshot site/_real_screenshots --source radio \
  --ftdi-lib-dir <folder with LibFT4222> --settle 20
```

`scripts/build_site.py` uses any scene listed in this folder's `manifest.json`
instead of the generated (emulator) one, and badges it "Real radio". Every
streaming screenshot on the site states its source: "Real radio" here, or
"Simulated: FT-710 emulator" for generated ones. Keep each PNG under 1 MiB.
