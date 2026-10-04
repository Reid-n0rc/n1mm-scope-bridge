# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
#
# Helpers of the installer smoke test (packaging/windows/smoke_lib.ps1, #181).

BeforeAll {
    . (Join-Path $PSScriptRoot '..\..\packaging\windows\smoke_lib.ps1')
}

Describe 'Get-PayloadPlan' {
    It 'plans the <payload> payload' -ForEach @(
        @{ payload = '';      expected = 'x64';   gui = $true;  downloads = $true;  lib = 'LibFT4222-64.dll'; machine = 0x8664; tasks = 'desktopicon,ftdidownload' }
        @{ payload = 'x64';   expected = 'x64';   gui = $true;  downloads = $true;  lib = 'LibFT4222-64.dll'; machine = 0x8664; tasks = 'desktopicon,ftdidownload' }
        @{ payload = 'arm64'; expected = 'arm64'; gui = $true;  downloads = $false; lib = 'LibFT4222-64.dll'; machine = 0xAA64; tasks = 'desktopicon' }
        @{ payload = 'x86';   expected = 'x86';   gui = $false; downloads = $true;  lib = 'LibFT4222.dll';    machine = 0x14C;  tasks = 'ftdidownload' }
    ) {
        $plan = Get-PayloadPlan $payload
        $plan.Expected | Should -BeExactly $expected
        $plan.HasGui | Should -Be $gui
        $plan.Downloads | Should -Be $downloads
        $plan.LibName | Should -BeExactly $lib
        $plan.Machine | Should -Be $machine
        $plan.Tasks | Should -BeExactly $tasks
    }
}

Describe 'Check' {
    BeforeEach { $failures = [System.Collections.Generic.List[string]]::new() }

    It 'records nothing for a passing check' {
        Check $true 'fine' 6>$null
        $failures.Count | Should -Be 0
    }

    It 'records a failing check' {
        Check $false 'broken' 6>$null
        Check (1 -eq 2) 'also broken' 6>$null
        $failures | Should -Be @('broken', 'also broken')
    }
}

Describe 'Get-PeMachine' {
    It 'reads the machine field of <name>' -ForEach @(
        @{ name = 'x64'; machine = 0x8664 }
        @{ name = 'ARM64'; machine = 0xAA64 }
        @{ name = 'x86'; machine = 0x14C }
    ) {
        $bytes = [byte[]]::new(0x100)
        [BitConverter]::GetBytes([int32]0x80).CopyTo($bytes, 0x3C)
        [byte[]][char[]]"PE`0`0" | ForEach-Object -Begin { $i = 0x80 } -Process { $bytes[$i++] = $_ }
        [BitConverter]::GetBytes([uint16]$machine).CopyTo($bytes, 0x84)
        $path = Join-Path $TestDrive "$name.exe"
        [IO.File]::WriteAllBytes($path, $bytes)
        Get-PeMachine $path | Should -Be $machine
    }

    It 'reads this PowerShell executable' {
        $exe = (Get-Process -Id $PID).Path
        Get-PeMachine $exe | Should -BeIn @(0x8664, 0xAA64, 0x14C)
    }
}
