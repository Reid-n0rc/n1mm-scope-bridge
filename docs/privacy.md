# Privacy notice

_Last updated: 2026-10-02_

N1MM Scope Bridge is a free, open-source program. **It collects no personal
data and sends nothing about you anywhere.** It has no telemetry, no
analytics, no update checks, no accounts and no advertising. This notice
explains the little network traffic there is and the third-party services
around the project, so you can exercise your rights under the GDPR and
similar laws.

## Who is responsible

The project is maintained by Reid Crowe, N0RC. Contact:

- general questions: open an issue at
  <https://github.com/Reid-n0rc/n1mm-scope-bridge/issues> (issues are public);
- private matters, including data protection requests: use GitHub's private
  reporting form at
  <https://github.com/Reid-n0rc/n1mm-scope-bridge/security/advisories/new>.

## What the program does with your data

Nothing. It processes no personal data, so no legal basis is needed for it,
and there is no data to access, correct or delete. It uses the network only
for things you configure:

1. **Spectrum data to N1MM Logger+:** the radio's scope data is sent over UDP
   to the N1MM+ address you set. By default that's this PC (`127.0.0.1`).
2. **Remote control (optional, off by default):** if you turn it on, the
   program listens for UDP commands, only from this PC unless you set a LAN
   address and an allow-list of client addresses.

Your settings are stored only on your PC
(`%APPDATA%\n1mm-scope-bridge\settings.json`). Uninstalling can remove them.

**Copy diagnostics** puts a bug-report summary on your clipboard. It never
leaves your PC unless you paste it somewhere. It redacts your user name and
home folder, IP addresses other than this PC's loopback, this PC's network
name, and the N1MM+ source name (often a call sign). Use **Copy diagnostics
including source name** only if you choose to share it.

The program never transmits on the radio and never changes the radio's
settings.

## Third parties you may deal with

These services process data under their own privacy policies. We receive
nothing from them.

| When | Service | What they see | Their policy |
|---|---|---|---|
| Visiting the website | GitHub Pages | your IP address and request details in server logs | [GitHub Privacy Statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement) |
| Downloading a release, opening issues | GitHub | your IP address; anything you post in an issue is **public** | [GitHub Privacy Statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement) |
| Installer's optional FTDI library download | Python Package Index (PyPI), run by the Python Software Foundation | your IP address and the download request | [PyPI privacy notice](https://policies.python.org/pypi.org/Privacy-Notice/) |
| Installing from the Microsoft Store (if published there) | Microsoft | your Microsoft account and install details | [Microsoft Privacy Statement](https://privacy.microsoft.com/privacystatement) |

The website itself sets **no cookies**, uses no local storage, and loads
nothing from other sites: no third-party fonts, scripts, analytics or
embedded media. Links to other sites only load them when you click.

Please don't post personal data (addresses, e-mail, phone numbers, logs from
other software) in public issues. Your call sign is fine if you choose to
share it.

## Your rights

Because the project holds no personal data about you, there is nothing for us
to give you, correct or delete. For data held by GitHub, PyPI or Microsoft,
use their privacy tools or contact them using the policies linked above. You
can also complain to your data protection authority.

## Children

The program and website aren't aimed at children and collect nothing from
anyone.

## Changes

Any change to what the program or website sends or loads requires an
approved issue and an update to this notice first. The date at the top shows
the latest version, and the history is in the
[repository](https://github.com/Reid-n0rc/n1mm-scope-bridge/commits/dev/docs/privacy.md).
