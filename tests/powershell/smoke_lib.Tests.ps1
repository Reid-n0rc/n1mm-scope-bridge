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

    It 'records every result when the caller keeps a $checks list' {
        $checks = [System.Collections.Generic.List[object]]::new()
        Check $true 'fine' 6>$null
        Check $false 'broken' 6>$null
        $checks.Name | Should -Be @('fine', 'broken')
        $checks.Ok | Should -Be @($true, $false)
    }
}

Describe 'Write-SmokeJUnit' {
    BeforeAll {
        function Read-Report([string]$path) { [xml](Get-Content -LiteralPath $path -Raw) }
        $script:Results = @(
            [pscustomobject]@{ Name = 'CLI exe installed'; Ok = $true }
            [pscustomobject]@{ Name = 'probe says "no radio" & <exits 1>'; Ok = $false }
        )
    }

    It 'writes one testcase per check' {
        $path = Join-Path $TestDrive 'smoke.xml'
        Write-SmokeJUnit $path 'installer.x64.amd64' $script:Results
        $suite = (Read-Report $path).testsuites.testsuite
        $suite.name | Should -BeExactly 'installer.x64.amd64'
        $suite.tests | Should -Be 2
        $suite.failures | Should -Be 1
        $suite.testcase[0].name | Should -BeExactly 'CLI exe installed'
        $suite.testcase[0].classname | Should -BeExactly 'installer.x64.amd64'
        $suite.testcase[0].failure | Should -BeNullOrEmpty
        $suite.testcase[1].name | Should -BeExactly 'probe says "no radio" & <exits 1>'
        $suite.testcase[1].failure.message | Should -BeExactly 'probe says "no radio" & <exits 1>'
    }

    It 'adds a failing testcase when the run stopped early' {
        $path = Join-Path $TestDrive 'aborted.xml'
        Write-SmokeJUnit $path 'installer.x86.amd64' $script:Results[0] 'setup.exe timed out'
        $suite = (Read-Report $path).testsuites.testsuite
        $suite.tests | Should -Be 2
        $suite.failures | Should -Be 1
        $suite.testcase[1].name | Should -BeExactly 'smoke test ran to completion'
        $suite.testcase[1].failure.message | Should -BeExactly 'setup.exe timed out'
    }

    It 'writes a valid empty suite' {
        $path = Join-Path $TestDrive 'empty.xml'
        Write-SmokeJUnit $path 'installer.arm64.arm64' @()
        $suite = (Read-Report $path).testsuites.testsuite
        $suite.tests | Should -Be 0
        $suite.failures | Should -Be 0
    }

    It 'writes UTF-8 without a byte-order mark' {
        $path = Join-Path $TestDrive 'bom.xml'
        Write-SmokeJUnit $path 's' $script:Results
        [IO.File]::ReadAllBytes($path)[0] | Should -Be ([byte][char]'<')
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
