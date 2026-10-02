# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
<#
.SYNOPSIS
  Walk the installer wizard on a Windows desktop and screenshot each page (#22).

.DESCRIPTION
  Starts the Inno Setup installer non-silently (per-user, into a temporary
  folder), drives it with UI Automation, captures every known wizard page with
  PrintWindow, then uninstalls silently. Writes PNGs plus a manifest.json in
  the same shape as `n1mm-scope-bridge gui --screenshot` (file, alt, caption,
  width, height) so the website builder can use them.

  Used by the release regression (scripts/regression_steps/85_installer_screenshots.py).
  Run with Windows PowerShell 5.1 (powershell.exe), which ships UI Automation.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File installer_screenshots.ps1 `
    -Installer dist\windows\n1mm-scope-bridge-setup-0.1.0.exe -OutDir shots
#>
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [int]$TimeoutSec = 240
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public static class WizardShot {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);

    // PW_RENDERFULLCONTENT (2) captures the window even when it is not in front.
    public static int[] Save(IntPtr hWnd, string path) {
        RECT r;
        GetWindowRect(hWnd, out r);
        int w = r.Right - r.Left, h = r.Bottom - r.Top;
        using (var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb)) {
            using (var g = Graphics.FromImage(bmp)) {
                IntPtr dc = g.GetHdc();
                PrintWindow(hWnd, dc, 2);
                g.ReleaseHdc(dc);
            }
            bmp.Save(path, ImageFormat.Png);
        }
        return new int[] { w, h };
    }
}
'@
[void][WizardShot]::SetProcessDPIAware()

$UIA = [System.Windows.Automation.AutomationElement]
$Tree = [System.Windows.Automation.TreeScope]
$Prop = [System.Windows.Automation.AutomationElement]

# Page heading (Inno Setup's Default.isl and installer.iss) -> scene, alt, caption.
$Pages = [ordered]@{
    'License Agreement'           = @('installer-license', 'Setup wizard showing the GNU General Public License version 3 on the License Agreement page', 'Setup shows the GPL license. Accept it to continue.')
    'Select Destination Location' = @('installer-destination', 'Setup wizard page for choosing the install folder', 'Pick where to install. The default is your own user folder, so no administrator rights are needed.')
    'Select Additional Tasks'     = @('installer-tasks', 'Setup wizard page with options for a desktop shortcut and starting with Windows', 'Optional desktop shortcut, and an option to start N1MM Scope Bridge when you sign in to Windows.')
    'FTDI LibFT4222 library'      = @('installer-ftdi', 'Setup wizard page asking for the folder containing FTDI''s LibFT4222 library', 'Point setup at your FTDI LibFT4222 download, or leave it empty and set it later in the app.')
    'Ready to Install'            = @('installer-ready', 'Setup wizard summary before installing', 'Check the summary, then choose Install.')
    'Completing the'              = @('installer-finished', 'Setup wizard finished page with an option to start N1MM Scope Bridge', 'Setup is complete. Start N1MM Scope Bridge from here or from the Start menu.')
}
$Required = 'installer-license', 'installer-tasks', 'installer-ftdi', 'installer-finished'

function Get-TopWindows {
    return @($UIA::RootElement.FindAll($Tree::Children, [System.Windows.Automation.Condition]::TrueCondition))
}

function Find-Wizard {
    # Inno Setup titles the wizard "Setup - <app name>" (some versions append the version).
    foreach ($w in Get-TopWindows) {
        if ($w.Current.Name -like 'Setup - N1MM Scope Bridge*') { return $w }
    }
    return $null
}

function Get-Names($window) {
    $all = $window.FindAll($Tree::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    return @($all | ForEach-Object { $_.Current.Name } | Where-Object { $_ })
}

function Get-Page($window) {
    $names = Get-Names $window
    foreach ($heading in $Pages.Keys) {
        if ($names | Where-Object { $_.StartsWith($heading) }) { return $heading }
    }
    if ($names | Where-Object { $_ -eq 'Installing' }) { return 'Installing' }
    return $null
}

function Find-Named($window, [string]$pattern) {
    # Any control type: Inno Setup's custom controls don't always map to the
    # UI Automation type you'd expect (for example its license radio buttons).
    foreach ($el in $window.FindAll($Tree::Descendants, [System.Windows.Automation.Condition]::TrueCondition)) {
        if ($el.Current.Name -match $pattern) { return $el }
    }
    return $null
}

function Use-Control($el) {
    # Select, press, or tick a control, whichever pattern it supports.
    foreach ($pat in [System.Windows.Automation.SelectionItemPattern]::Pattern,
                     [System.Windows.Automation.InvokePattern]::Pattern,
                     [System.Windows.Automation.TogglePattern]::Pattern) {
        $obj = $null
        if ($el.TryGetCurrentPattern($pat, [ref]$obj)) {
            if ($pat -eq [System.Windows.Automation.SelectionItemPattern]::Pattern) { $obj.Select() }
            elseif ($pat -eq [System.Windows.Automation.InvokePattern]::Pattern) { $obj.Invoke() }
            else { $obj.Toggle() }
            return $true
        }
    }
    return $false
}

function Send-Accelerator($window, [string]$keys) {
    # Wizard keyboard shortcuts (for example Alt+N for "&Next >").
    Add-Type -AssemblyName System.Windows.Forms
    [void][WizardShot]::SetForegroundWindow([IntPtr]$window.Current.NativeWindowHandle)
    Start-Sleep -Milliseconds 200
    [System.Windows.Forms.SendKeys]::SendWait($keys)
}

function Activate($window, [string]$pattern, [string]$keys) {
    $el = Find-Named $window $pattern
    if ($el -and (Use-Control $el)) { return }
    Write-Host "using keyboard $keys for '$pattern'"
    Send-Accelerator $window $keys
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$FakeFtdi = Join-Path ([IO.Path]::GetTempPath()) 'LibFT4222-placeholder'
New-Item -ItemType Directory -Force -Path $FakeFtdi | Out-Null
New-Item -ItemType File -Force -Path (Join-Path $FakeFtdi ('LibFT4222' + '-64.dll')) | Out-Null
$InstallDir = Join-Path ([IO.Path]::GetTempPath()) ('n1mm-shots-' + [guid]::NewGuid().ToString('N'))
$proc = Start-Process -FilePath $Installer -ArgumentList '/CURRENTUSER', "/DIR=`"$InstallDir`"", '/NORESTART' -PassThru

$manifest = [ordered]@{}
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$last = $null
$lastLog = Get-Date
$dumped = @{}
try {
    while ((Get-Date) -lt $deadline) {
        $window = Find-Wizard
        if ((Get-Date) -gt $lastLog.AddSeconds(10)) {
            # Diagnostics for CI logs: what the desktop and the wizard expose.
            $lastLog = Get-Date
            Write-Host ('top-level windows: ' + ((Get-TopWindows | ForEach-Object { "'" + $_.Current.Name + "'" }) -join ', '))
            if ($window) { Write-Host ('wizard names: ' + ((Get-Names $window | Select-Object -First 40) -join ' | ')) }
        }
        if (-not $window) { Start-Sleep -Milliseconds 300; continue }
        # Leaving the FTDI folder empty asks whether to open FTDI's download page;
        # answer No so CI never launches a browser.
        if (Find-Named $window "^Open FTDI's LibFT4222 download page") {
            Activate $window '^&?No$' 'n'
            Start-Sleep -Milliseconds 500
            continue
        }
        $page = Get-Page $window
        if (-not $page) {
            $key = (Get-Names $window | Select-Object -First 6) -join '|'
            if (-not $dumped.ContainsKey($key)) {
                $dumped[$key] = $true
                Write-Host ('unrecognised wizard page, names: ' + ((Get-Names $window | Select-Object -First 40) -join ' | '))
            }
        }
        if (-not $page -or $page -eq $last -or $page -eq 'Installing') { Start-Sleep -Milliseconds 300; continue }
        Start-Sleep -Milliseconds 700   # let the page finish painting
        $scene, $alt, $caption = $Pages[$page]
        $hwnd = [IntPtr]$window.Current.NativeWindowHandle
        [void][WizardShot]::SetForegroundWindow($hwnd)
        $size = [WizardShot]::Save($hwnd, (Join-Path $OutDir "$scene.png"))
        $manifest[$scene] = [ordered]@{ file = "$scene.png"; alt = $alt; caption = $caption; width = $size[0]; height = $size[1] }
        Write-Host "captured $scene ($($size[0])x$($size[1]))"
        $last = $page

        Write-Host ("page '$page' names: " + ((Get-Names $window | Select-Object -First 40) -join ' | '))
        switch ($page) {
            'License Agreement' {
                Activate $window '^I &?accept' '%a'
                Start-Sleep -Milliseconds 300
                Activate $window '^&?Next' '%n'
            }
            'Ready to Install' { Activate $window '^&?Install$' '%i' }
            'Completing the' {
                # Don't launch the app from the finished page.
                $launch = Find-Named $window '^&?Start '
                if ($launch) {
                    $obj = $null
                    if ($launch.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$obj) -and $obj.Current.ToggleState -eq 'On') { $obj.Toggle() }
                }
                Activate $window '^&?Finish' '%f'
            }
            'FTDI LibFT4222 library' {
                # Point the page at a placeholder folder so setup doesn't stop to ask
                # about FTDI's download page. The empty file exists only on this
                # machine for this run; the silent uninstall below removes the copy.
                # Inno's text box isn't always typed "Edit"; find whatever accepts a value.
                $hasValue = New-Object System.Windows.Automation.PropertyCondition($Prop::IsValuePatternAvailableProperty, $true)
                $edit = $window.FindFirst($Tree::Descendants, $hasValue)
                if ($edit) {
                    $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($FakeFtdi)
                } else {
                    Write-Host 'typing the FTDI folder into the focused box'
                    Send-Accelerator $window ($FakeFtdi -replace '([+^%~(){}\[\]])', '{$1}')
                }
                Start-Sleep -Milliseconds 300
                Activate $window '^&?Next' '%n'
            }
            default { Activate $window '^&?Next' '%n' }
        }
        if ($page -eq 'Completing the') { break }
    }
    $proc.WaitForExit(60000) | Out-Null
}
finally {
    Get-Process -Name 'N1MM Scope Bridge' -ErrorAction SilentlyContinue | Stop-Process -Force
    $uninstaller = Get-ChildItem -Path $InstallDir -Filter 'unins*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($uninstaller) {
        Start-Process $uninstaller.FullName -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
    }
    if (-not $proc.HasExited) { $proc | Stop-Process -Force }
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $FakeFtdi
}

# UTF-8 without a BOM (Windows PowerShell 5.1's -Encoding utf8 adds one).
[IO.File]::WriteAllText((Join-Path $OutDir 'manifest.json'), ($manifest | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding $false))
$missing = @($Required | Where-Object { -not $manifest.Contains($_) })
if ($missing.Count -gt 0) {
    Write-Error "Installer screenshots missing: $($missing -join ', ')"
    exit 1
}
Write-Host "Installer screenshots: $($manifest.Count) pages in $OutDir"
