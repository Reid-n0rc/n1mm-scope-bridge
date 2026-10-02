# Real-radio screenshots

Screenshots captured from a real radio (receive only) with:

```
n1mm-scope-bridge gui --screenshot site/_real_screenshots --source radio \
  --ftdi-lib-dir <folder with LibFT4222> --settle 20
```

The live recording on the home page (`main-window-live.*`, #124) was rendered
from a capture of the real radio, so it can be regenerated without the radio:

```
n1mm-scope-bridge record --frames 700 ft710-live.cap      # at the radio (receive only)
n1mm-scope-bridge gui --record site/_real_screenshots --source replay --replay ft710-live.cap
```

It records every radio frame (about 11 per second) as MP4 and WebM video (needs
ffmpeg), with a smaller GIF fallback. The capture itself is not committed (2.9 MB, over the 1 MiB file limit).

`scripts/build_site.py` uses any scene listed in this folder's `manifest.json`
instead of the generated (emulator) one, and badges it "Real radio". Every
streaming screenshot on the site states its source: "Real radio" here, or
"Simulated: FT-710 emulator" for generated ones. Keep each file under 1 MiB (the `--record` defaults do).
