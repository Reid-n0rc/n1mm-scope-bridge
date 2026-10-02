# Security Policy

## Scope

`n1mm-scope-bridge` runs on an operator's station PC. It reads scope data from
a USB device and sends UDP datagrams, by default to `127.0.0.1:13064`. The
security-relevant surface is:

- **Network output.** The bridge *sends* UDP to N1MM+. Its only listening
  socket is the optional **UDP remote control** (#30), which is **off by
  default**. When enabled it binds to `127.0.0.1` unless the operator sets
  one specific interface IP *and* an allow-list of client IPs. Binding to all
  interfaces (`0.0.0.0`, `::`, or empty) is always refused; requests from any other
  address are ignored; requests are capped at 512 bytes; and no command can
  transmit or change radio state. A way around these limits is a
  vulnerability.
- **Untrusted input parsing.** Frames from the radio, and capture files given
  to `--replay`, are parsed as untrusted bytes. A malformed frame must be
  rejected cleanly, never cause an out-of-bounds read or a crash loop.
- **Native libraries.** LibFT4222 and D2XX are loaded from the system library
  path or from a path the user configures. The bridge must never download
  native code, and the repository never ships it.
- **Radio safety.** The bridge must never transmit or change radio state (see
  AGENTS.md, rule 8).

The program itself uses no secrets (CI secrets are listed below). If a future feature needs one (for
example remote LAN radio credentials), it must come from the environment or
the OS credential store at runtime and never be committed.

## CI secrets

The only CI secret is `CODECOV_TOKEN`, the Codecov upload token. It is stored
as a GitHub repository secret and is never written to the repository. Pull
requests from forks don't receive secrets, so they skip the coverage upload;
that never fails CI.

## Reporting a vulnerability

This repository uses **GitHub private vulnerability reporting**:

1. Open the repository's **Security** tab and choose **Report a
   vulnerability**, or go to
   <https://github.com/Reid-n0rc/n1mm-scope-bridge/security/advisories/new>.
2. Include the affected version or commit, reproduction steps, and the impact.

**Do not** report vulnerabilities in public issues, pull requests, or
discussions.

The maintainer aims to acknowledge reports within 7 days. Fixes are
coordinated privately and disclosed through a GitHub Security Advisory once a
fixed release is available. Reporters are credited unless they ask not to be.

## Supported versions

Only the latest release on `master` receives security fixes.
