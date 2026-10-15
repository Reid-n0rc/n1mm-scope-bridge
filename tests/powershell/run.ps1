# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
#
# Runs the Pester tests for the Windows packaging helpers (#181) with a pinned,
# hash-checked Pester, writing JaCoCo coverage and JUnit results:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tests/powershell/run.ps1
#
# Windows PowerShell 5.1 is the target: the installer runs the helpers with it.

param(
    [string]$Coverage = 'pester-coverage.xml',
    [string]$JUnit = 'pester-junit.xml'
)

$ErrorActionPreference = 'Stop'
$PesterVersion = '5.9.1'
$PesterSha256 = '8dd4060fc3bc895f05bd655e4ab82abe346de54a4e6415dfb727cc8378672b69'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$Helpers = Join-Path $Root 'packaging\windows'

$cache = Join-Path ([IO.Path]::GetTempPath()) "n1mm-pester-$PesterVersion"
$manifest = Join-Path $cache 'Pester.psd1'
if (-not (Test-Path $manifest)) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $package = Join-Path ([IO.Path]::GetTempPath()) "pester-$PesterVersion.zip"
    Invoke-WebRequest -UseBasicParsing -Uri "https://www.powershellgallery.com/api/v2/package/Pester/$PesterVersion" -OutFile $package
    $hash = (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $PesterSha256) { throw "Pester $PesterVersion package hash mismatch: $hash" }
    Expand-Archive -LiteralPath $package -DestinationPath $cache -Force
    Remove-Item -LiteralPath $package
}
Import-Module $manifest -Force

$config = New-PesterConfiguration
$config.Run.Path = $PSScriptRoot
$config.Run.Exit = $true
$config.Output.Verbosity = 'Detailed'
$config.TestResult.Enabled = $true
$config.TestResult.OutputFormat = 'JUnitXml'
$config.TestResult.OutputPath = $JUnit
$config.CodeCoverage.Enabled = $true
$config.CodeCoverage.Path = @('ftdi_install.ps1', 'ftdi_driver.ps1', 'smoke_lib.ps1' | ForEach-Object { Join-Path $Helpers $_ })
$config.CodeCoverage.OutputFormat = 'JaCoCo'
$config.CodeCoverage.OutputPath = $Coverage
Invoke-Pester -Configuration $config
