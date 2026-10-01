# N1MM+ external spectrum packet

Source: N1MM+ manual, *External UDP Messages*,
<https://n1mmwp.hamdocs.com/appendices/external-udp-broadcasts/> (facts only,
no code copied).

- Transport: one UDP datagram per spectrum line, sent to **port 13064** on the
  N1MM+ PC (default `127.0.0.1`)
- Encoding: UTF-8 XML

```xml
<?xml version="1.0" encoding="utf-8"?>
<Spectrum>
  <app>n1mm-scope-bridge</app>
  <Name>FT-710</Name>
  <LowScopeFrequency>14000</LowScopeFrequency>
  <HighScopeFrequency>14100</HighScopeFrequency>
  <ScalingFactor>0.3125</ScalingFactor>
  <DataCount>850</DataCount>
  <SpectrumData>0,3,7,...</SpectrumData>
</Spectrum>
```

| Element | Meaning |
|---------|---------|
| `app` | Name of the sending program |
| `Name` | Source name. N1MM+ shows it in the UI and matches it in **External Source Name** |
| `LowScopeFrequency` / `HighScopeFrequency` | Frequencies of the first and last bins, **in kHz** |
| `ScalingFactor` | Multiplier that converts each level to dB for display |
| `DataCount` | Number of values in `SpectrumData` |
| `SpectrumData` | Comma-separated integer levels, 0–65535 |

## Rules this project follows

- `DataCount` must equal the number of values sent. The encoder rejects a
  mismatch.
- Frequencies are written in kHz with no more than 3 decimals (1 Hz
  resolution), and trailing zeros are trimmed.
- Rate: the N1MM team notes that Icom sends about 3 per second, which is
  adequate, and asks for no more than 5–10 per second. The bridge defaults
  to **4 per second** and caps the rate at 10.
- XML special characters in `Name` and `app` are escaped.

## Open questions (resolve during hardware validation)

- The best `ScalingFactor` for the FT-710's 0–255 levels. The starting guess
  is `0.3125`, which maps 256 steps to about 80 dB. Calibrate it against the
  radio's own scope reference level.
