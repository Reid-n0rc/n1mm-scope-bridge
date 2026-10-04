# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
#
# Helpers for smoke_test.ps1, dot-sourced so Pester can test them (#181):
#   . (Join-Path $PSScriptRoot 'smoke_lib.ps1')

# What the installer smoke test expects from a payload (#149). Without -Payload,
# setup picks x64 (also on Windows on ARM).
function Get-PayloadPlan([string]$Payload) {
    $expected = if ($Payload) { $Payload } else { 'x64' }
    $downloads = $expected -ne 'arm64'  # no verifiable ARM64 FTDI download exists
    $tasks = if ($expected -eq 'x86') { 'ftdidownload' } elseif ($downloads) { 'desktopicon,ftdidownload' } else { 'desktopicon' }
    return [pscustomobject]@{
        Expected  = $expected
        HasGui    = $expected -ne 'x86'
        Downloads = $downloads
        LibName   = $(if ($expected -eq 'x86') { 'LibFT4222.dll' } else { 'LibFT4222-64.dll' })
        Machine   = @{ 'x64' = 0x8664; 'arm64' = 0xAA64; 'x86' = 0x14C }[$expected]
        Tasks     = $tasks
    }
}

# Records one check; failures go to the caller's $failures list.
function Check([bool]$ok, [string]$what) {
    if ($ok) { Write-Host "ok   - $what" } else { Write-Host "FAIL - $what"; $failures.Add($what) }
}

# The PE header's Machine field (0x8664 x64, 0xAA64 ARM64, 0x14C x86).
function Get-PeMachine([string]$path) {
    $bytes = [IO.File]::ReadAllBytes($path)
    $pe = [BitConverter]::ToInt32($bytes, 0x3C)
    return [BitConverter]::ToUInt16($bytes, $pe + 4)
}
