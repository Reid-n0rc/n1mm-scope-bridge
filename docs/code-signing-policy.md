# Code signing policy

**Planned:** Free code signing provided by SignPath.io, certificate by SignPath Foundation.

The project has applied to the [SignPath Foundation](https://signpath.org/)
for free code signing (issue #130). Until signing is active, the Windows
installer and programs are **not** code-signed, and Windows SmartScreen shows
a warning when you run them. This page describes the policy that will apply
to every signed release.

## Team roles

| Role | Members | Responsibility |
|---|---|---|
| Authors | Reid Crowe, N0RC ([@Reid-n0rc](https://github.com/Reid-n0rc)) | Trusted to change the source code |
| Reviewers | Reid Crowe, N0RC | Review and approve changes from anyone else |
| Approvers | Reid Crowe, N0RC | Approve each signing request |

AI coding agents work on this project only through the maintainer's GitHub
account. Every change reaches the release branch through a pull request that
must pass CI, CodeQL code scanning, secret scanning and dependency review.
Signing a release always needs the maintainer's manual approval.

All team members use multi-factor authentication on GitHub and on SignPath.

## What gets signed

- The Windows installer (`n1mm-scope-bridge-setup-<version>.exe`).
- The program files inside it (`N1MM Scope Bridge.exe` and
  `n1mm-scope-bridge.exe`).

These files are built by GitHub Actions from this repository's tagged source
code. Nothing is built or signed on a personal computer.

Signed files contain no proprietary code. FTDI's LibFT4222 and D2XX
libraries, which the program needs to talk to the radio, are **never** bundled
in the installer or the program. They come from FTDI: either you install
them yourself, or the installer downloads FTDI's own signed copy if you leave
that option ticked.

## How you can check a release

- Each release lists SHA-256 checksums (`SHA256SUMS`).
- GitHub build provenance attestations show that the files were built by this
  repository's release workflow from the tagged commit:
  `gh attestation verify <file> --repo Reid-n0rc/n1mm-scope-bridge`.
- The full source code for each release is attached to the release.

See also the [privacy statement](privacy.md).
