# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
#
# Installer smoke test (issue #20): silent per-user install into a temp
# folder, check files, shortcuts and the uninstall entry, run the installed CLI
# (legal notices + emulator frames into a UDP listener) and the GUI self-test,
# then uninstall silently and check everything is gone except the settings.
# The install runs with the FTDI download task (#133): setup must download
# FTDI's signed LibFT4222/D2XX into the program folder, and probe must then load
# them and report that no radio is connected.
#
#   pwsh packaging/windows/smoke_test.ps1 -Installer dist\windows\n1mm-scope-bridge-setup-0.1.0.exe

param(
    [Parameter(Mandatory = $true)][string]$Installer
)

$ErrorActionPreference = 'Stop'
$AppId = '{5B454E52-482B-4DB9-9888-C9C98FCD1306}_is1'
$AppName = 'N1MM Scope Bridge'
$Dir = Join-Path $env:RUNNER_TEMP ("n1mm-sb-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
if (-not $env:RUNNER_TEMP) { $Dir = Join-Path $env:TEMP ("n1mm-sb-" + [guid]::NewGuid().ToString('N').Substring(0, 8)) }
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppId"
# Inno Setup puts the shortcuts in a {group} folder named after the app.
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) "$AppName\$AppName.lnk"
$Desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk"
$failures = [System.Collections.Generic.List[string]]::new()

function Check([bool]$ok, [string]$what) {
    if ($ok) { Write-Host "ok   - $what" } else { Write-Host "FAIL - $what"; $failures.Add($what) }
}

function Wait-Process-Exit([string]$file, [string[]]$arguments, [int]$timeoutSec = 120, [string]$logFile = '') {
    $p = Start-Process -FilePath $file -ArgumentList $arguments -PassThru -WindowStyle Hidden
    if (-not $p.WaitForExit($timeoutSec * 1000)) {
        $p.Kill()
        $stuck = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'powershell|setup|n1mm' }
        foreach ($proc in $stuck) {
            Write-Host "still running: $($_.ProcessName) $($proc.ProcessName) pid=$($proc.Id) window='$($proc.MainWindowTitle)'"
        }
        # Name every top-level window, to see any dialog setup is waiting on.
        Add-Type -AssemblyName UIAutomationClient
        $root = [System.Windows.Automation.AutomationElement]::RootElement
        $all = $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
        foreach ($w in $all) {
            $names = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition) |
                ForEach-Object { $_.Current.Name } | Where-Object { $_ } | Select-Object -First 12
            Write-Host ("window '" + $w.Current.Name + "': " + ($names -join ' | '))
        }
        if ($logFile -and (Test-Path $logFile)) {
            Write-Host "--- log ($((Get-Item $logFile).Length) bytes) ---"
            Get-Content $logFile -Tail 80
        } else { Write-Host '--- no log file ---' }
        $stuck | Where-Object { $_.ProcessName -match 'setup' } | Stop-Process -Force -ErrorAction SilentlyContinue
        throw "$file timed out"
    }
    return $p.ExitCode
}

# --- install ------------------------------------------------------------------------
# An earlier release candidate could add a start-with-Windows Run value; setup must remove it (#136).
New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name $AppName -Value 'stale-from-rc1' -PropertyType String -Force | Out-Null
$log = Join-Path ([IO.Path]::GetTempPath()) 'n1mm-sb-install.log'
$code = Wait-Process-Exit $Installer @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER',
    "/DIR=`"$Dir`"", '/TASKS=desktopicon,ftdidownload', "/LOG=`"$log`"") -timeoutSec 300 -logFile $log
Check ($code -eq 0) "silent install exits 0 (got $code)"
if ($code -ne 0) {
    Write-Host '--- install log ---'
    if (Test-Path $log) { Get-Content $log -Tail 60 } else { Write-Host '(no log written)' }
    exit 1
}
$cli = Join-Path $Dir 'n1mm-scope-bridge.exe'
$gui = Join-Path $Dir "$AppName.exe"
Check (Test-Path $cli) 'CLI exe installed'
Check (Test-Path $gui) 'GUI exe installed'
foreach ($f in 'LICENSE', 'NOTICE', 'THIRD_PARTY.md') { Check (Test-Path (Join-Path $Dir "licenses\$f")) "licenses\$f installed" }
# FTDI's DLLs come only from setup's download (never from our installer).
$expectedSigners = @{ 'LibFT4222-64.dll' = 'Future Technology Devices International'; 'ftd2xx.dll' = 'Microsoft Windows Hardware Compatibility' }
foreach ($name in $expectedSigners.Keys) {
    $path = Join-Path $Dir $name
    Check (Test-Path $path) "$name downloaded into the program folder"
    if (Test-Path $path) {
        $sig = Get-AuthenticodeSignature -LiteralPath $path
        Check ($sig.Status -eq 'Valid' -and $sig.SignerCertificate.Subject -like "*$($expectedSigners[$name])*") "$name signature valid ($($sig.Status), $($sig.SignerCertificate.Subject))"
    }
}
$extra = Get-ChildItem -Path $Dir -Recurse -File | Where-Object { $_.Name -match '(?i)(ft4222|ftd2xx)' -and $_.Extension -eq '.dll' -and $_.DirectoryName -ne (Get-Item $Dir).FullName }
Check ($null -eq $extra) 'no FTDI binaries anywhere except the downloaded pair'
if (Test-Path $log) { Check ((Get-Content $log -Raw) -match 'FTDI download: LibFT4222-64.dll and ftd2xx.dll installed') 'install log records the verified FTDI download' }
Check (Test-Path $StartMenu) 'Start menu shortcut created'
Check (Test-Path $Desktop) 'desktop shortcut created'
Check (Test-Path $UninstallKey) 'uninstall entry registered (per user)'
# The program never starts with Windows (#136): no Run entry, even after an upgrade.
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
Check ($null -eq (Get-ItemProperty -Path $RunKey -Name $AppName -ErrorAction SilentlyContinue)) 'no start-with-Windows Run entry (stale RC value removed)'

# --- run the installed app ----------------------------------------------------------------
$version = & $cli --version | Out-String
Check ($LASTEXITCODE -eq 0 -and $version -match 'ABSOLUTELY NO WARRANTY') 'installed CLI --version shows the GPL notice'

$udp = [System.Net.Sockets.UdpClient]::new([System.Net.IPEndPoint]::new([System.Net.IPAddress]::Loopback, 0))
$udp.Client.ReceiveBufferSize = 2MB
$port = $udp.Client.LocalEndPoint.Port
& $cli run --emulator --duration 2 --rate 10 --port $port | Out-Null
$runCode = $LASTEXITCODE
$udp.Client.ReceiveTimeout = 1000
$packets = 0
try {
    while ($true) {
        $remote = [System.Net.IPEndPoint]::new([System.Net.IPAddress]::Any, 0)
        $bytes = $udp.Receive([ref]$remote)
        if ([Text.Encoding]::UTF8.GetString($bytes) -match '<Spectrum>') { $packets++ }
    }
} catch [System.Net.Sockets.SocketException] { } finally { $udp.Close() }
Check ($runCode -eq 0 -and $packets -ge 3) "installed CLI streams emulator frames to UDP (exit $runCode, $packets packets)"

# With FTDI's DLLs installed, probe loads them and finds no radio (CI has none).
$ErrorActionPreference = 'Continue'  # probe writes its error to stderr and exits 1
$probe = & $cli probe 2>&1 | Out-String
$probeCode = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
Check ($probeCode -eq 1 -and $probe -match "Could not open 'FT4222 A'" -and $probe -notmatch "Could not load FTDI") "installed CLI probe loads FTDI's library and reports no radio ($($probe.Trim()))"

$selfTest = Wait-Process-Exit $gui @('--self-test')
Check ($selfTest -eq 0) "installed GUI --self-test exits 0 (got $selfTest)"

# --- uninstall -----------------------------------------------------------------------------
$settings = Join-Path $env:APPDATA 'n1mm-scope-bridge'
$hadSettings = Test-Path $settings
$code = Wait-Process-Exit (Join-Path $Dir 'unins000.exe') @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
Check ($code -eq 0) "silent uninstall exits 0 (got $code)"
# The uninstaller re-launches itself from a temp copy; wait for the files to go.
$deadline = (Get-Date).AddSeconds(60)
while ((Test-Path $cli) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
Check (-not (Test-Path $cli)) 'program files removed'
Check (-not (Test-Path (Join-Path $Dir 'LibFT4222-64.dll'))) 'downloaded FTDI DLLs removed by uninstall'
Check (-not (Test-Path $StartMenu)) 'Start menu shortcut removed'
Check (-not (Test-Path $Desktop)) 'desktop shortcut removed'
Check (-not (Test-Path $UninstallKey)) 'uninstall entry removed'
if ($hadSettings) { Check (Test-Path $settings) 'settings kept by silent uninstall' }

if ($failures.Count -gt 0) {
    Write-Host "`n$($failures.Count) check(s) failed"
    if (Test-Path $log) { Get-Content $log -Tail 40 }
    exit 1
}
Write-Host "`nInstaller smoke test passed"
# GitHub's pwsh wrapper exits with the last native $LASTEXITCODE (probe: 1 by design).
exit 0
