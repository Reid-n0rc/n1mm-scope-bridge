# Privacy statement

N1MM Scope Bridge collects no personal data and sends nothing about you
anywhere. It has no telemetry, no update checks, no accounts and no
advertising.

It uses the network only for these things, all of which you control:

1. **Spectrum data to N1MM Logger+:** the radio's scope data is sent over UDP
   to the N1MM+ address you configure. By default that's this PC
   (`127.0.0.1`).
2. **Remote control (optional, off by default):** if you turn it on, the
   program listens for UDP commands, by default only from this PC.
3. **FTDI library download (installer only):** if the installer offers to
   download FTDI's libraries and you leave that option
   ticked, the installer downloads FTDI's LibFT4222 and D2XX libraries
   during installation.

Your settings are stored only on your PC
(`%APPDATA%\n1mm-scope-bridge\settings.json`).

The program never transmits on the radio and never changes the radio's
settings.

Questions: open an issue at
<https://github.com/Reid-n0rc/n1mm-scope-bridge/issues>.
