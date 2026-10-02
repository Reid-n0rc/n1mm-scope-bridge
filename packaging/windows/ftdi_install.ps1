# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
#
# Installer helper (issue #133): extract FTDI's LibFT4222-64.dll and ftd2xx.dll
# from the wheel the installer just downloaded (SHA-256 already verified by
# Inno Setup), check both Authenticode signatures, and copy them into the
# program folder. Writes "OK" or "ERROR: <reason>" to -Result and exits 0/1.
# FTDI's DLLs are never part of our installer; the user's setup downloads them.

param(
    [Parameter(Mandatory = $true)][string]$Wheel,
    [Parameter(Mandatory = $true)][string]$Dest,
    [Parameter(Mandatory = $true)][string]$LibSigner,
    [Parameter(Mandatory = $true)][string]$D2xxSigner,
    [Parameter(Mandatory = $true)][string]$Result
)

$ErrorActionPreference = 'Stop'
$work = Join-Path ([IO.Path]::GetTempPath()) ("n1mm-ftdi-" + [guid]::NewGuid().ToString('N').Substring(0, 8))

function Finish([string]$message, [int]$code) {
    # ASCII without a byte-order mark, so setup can compare the text exactly.
    [IO.File]::WriteAllText($Result, $message, [Text.Encoding]::ASCII)
    if (Test-Path $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
    exit $code
}

try {
    # If PowerShell 7 is installed, Windows PowerShell can inherit its module path
    # and fail to load Get-AuthenticodeSignature; use Windows PowerShell's own modules.
    $env:PSModulePath = (@("$PSHOME\Modules", [Environment]::GetEnvironmentVariable('PSModulePath', 'Machine')) -join ';')
    Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -Force
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    New-Item -ItemType Directory -Path $work | Out-Null
    $wanted = @{ 'LibFT4222-64.dll' = $LibSigner; 'ftd2xx.dll' = $D2xxSigner }
    $zip = [IO.Compression.ZipFile]::OpenRead($Wheel)
    try {
        foreach ($name in $wanted.Keys) {
            $entries = @($zip.Entries | Where-Object { $_.FullName -replace '\\', '/' -match "(^|/)$([regex]::Escape($name))$" })
            if ($entries.Count -ne 1) { Finish "ERROR: expected one $name in the download, found $($entries.Count)" 1 }
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entries[0], (Join-Path $work $name), $true)
        }
    } finally { $zip.Dispose() }

    foreach ($name in $wanted.Keys) {
        $sig = Get-AuthenticodeSignature -LiteralPath (Join-Path $work $name)
        if ($sig.Status -ne 'Valid') { Finish "ERROR: $name signature is not valid ($($sig.Status))" 1 }
        $subject = $sig.SignerCertificate.Subject
        if ($subject -notlike "*$($wanted[$name])*") { Finish "ERROR: $name is signed by '$subject', expected '$($wanted[$name])'" 1 }
    }

    foreach ($name in $wanted.Keys) { Copy-Item -LiteralPath (Join-Path $work $name) -Destination (Join-Path $Dest $name) -Force }
    Finish 'OK' 0
} catch {
    Finish "ERROR: $($_.Exception.Message)" 1
}
