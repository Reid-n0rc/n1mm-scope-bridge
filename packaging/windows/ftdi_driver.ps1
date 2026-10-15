# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
#
# FTDI USB driver helper (issue #152). Modes:
#   Check    Is an FTDI D2XX driver package for USB\VID_0403&PID_601C (the
#            radio's FT4222H scope interface) in the Windows driver store?
#            Writes INSTALLED, MISSING or ERROR: <reason>. No admin needed.
#   Verify   Expand the downloaded CAB (SHA-256 already checked by the caller),
#            check the catalog's Authenticode signature and that the INF covers
#            the FT4222H. Writes OK or ERROR: <reason>. No admin needed.
#   Install  Verify, then `pnputil /add-driver <inf> /install`. Needs admin; the
#            installer runs this mode elevated only when the user ticks
#            "Install FTDI USB driver (needs administrator)".
# The result goes to -Result as ASCII text; exit code 0 = success.
# The driver package comes from Microsoft Update Catalog (FTDI's WHQL driver);
# it is never bundled in our installer.

param(
    [Parameter(Mandatory = $true)][ValidateSet('Check', 'Verify', 'Install')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$Result,
    [string]$Cab = '',
    [string]$Signer = 'Microsoft Windows Hardware Compatibility Publisher',
    [string]$Inf = 'ftdibus.inf',
    [string]$Catalog = 'ftdibus.cat',
    [string]$HardwareId = 'USB\VID_0403&PID_601C'
)

$ErrorActionPreference = 'Stop'
$work = Join-Path ([IO.Path]::GetTempPath()) ("n1mm-ftdidrv-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$pnputil = Join-Path $env:SystemRoot 'System32\pnputil.exe'
if (-not (Test-Path $pnputil)) { $pnputil = Join-Path $env:SystemRoot 'Sysnative\pnputil.exe' }

function Finish([string]$message, [int]$code) {
    [IO.File]::WriteAllText($Result, $message, [Text.Encoding]::ASCII)
    if (Test-Path $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
    exit $code
}

# Thin wrappers around the native tools, so tests can mock them (#181).
function Invoke-Pnputil([string]$exe, [string[]]$arguments) {
    return (& $exe @arguments 2>&1 | Out-String)
}

function Invoke-Expand([string]$cabPath, [string]$dest) {
    & (Join-Path $env:SystemRoot 'System32\expand.exe') -F:* $cabPath $dest | Out-Null
}

function Test-FtdiDriverInstalled {
    # pnputil lists every third-party driver package; FTDI's bus driver INF is
    # published as oemNN.inf with "Original Name: ftdibus.inf".
    $out = Invoke-Pnputil $pnputil @('/enum-drivers')
    return ($out -match '(?im)^\s*Original Name:\s*ftdibus\.inf\s*$')
}

function Expand-AndVerify {
    if (-not $Cab -or -not (Test-Path -LiteralPath $Cab)) { Finish "ERROR: driver package not found: $Cab" 1 }
    New-Item -ItemType Directory -Path $work | Out-Null
    Invoke-Expand $Cab $work
    $infPath = Join-Path $work $Inf
    $catPath = Join-Path $work $Catalog
    if (-not (Test-Path $infPath)) { Finish "ERROR: $Inf is missing from the driver package" 1 }
    if (-not (Test-Path $catPath)) { Finish "ERROR: $Catalog is missing from the driver package" 1 }
    $env:PSModulePath = (@("$PSHOME\Modules", [Environment]::GetEnvironmentVariable('PSModulePath', 'Machine')) -join ';')
    Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -Force
    $sig = Get-AuthenticodeSignature -LiteralPath $catPath
    if ($sig.Status -ne 'Valid') { Finish "ERROR: $Catalog signature is not valid ($($sig.Status))" 1 }
    $subject = $sig.SignerCertificate.Subject
    if ($subject -notlike "*$Signer*") { Finish "ERROR: $Catalog is signed by '$subject', expected '$Signer'" 1 }
    $infText = Get-Content -LiteralPath $infPath -Raw
    if ($infText -notlike "*$HardwareId*") { Finish "ERROR: $Inf does not list $HardwareId (FT4222H)" 1 }
    return $infPath
}

try {
    switch ($Mode) {
        'Check' {
            if (Test-FtdiDriverInstalled) { Finish 'INSTALLED' 0 } else { Finish 'MISSING' 0 }
        }
        'Verify' {
            Expand-AndVerify | Out-Null
            Finish 'OK' 0
        }
        'Install' {
            $infPath = Expand-AndVerify
            $out = Invoke-Pnputil $pnputil @('/add-driver', $infPath, '/install')
            $code = $LASTEXITCODE
            # 0 = added; 259 (ERROR_NO_MORE_ITEMS) = already up to date; 3010 = reboot required.
            if ($code -in 0, 259, 3010) {
                if (Test-FtdiDriverInstalled) { Finish 'OK' 0 }
                Finish "ERROR: pnputil reported success ($code) but ftdibus.inf is not in the driver store" 1
            }
            Finish ("ERROR: pnputil /add-driver failed with exit code $code`: " + ($out.Trim() -replace '\s+', ' ')) 1
        }
    }
} catch {
    Finish "ERROR: $($_.Exception.Message)" 1
}
