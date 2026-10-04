# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
#
# packaging/windows/ftdi_driver.ps1 (#152) with pnputil, expand.exe and
# Get-AuthenticodeSignature mocked: nothing is installed (#181).

BeforeAll {
    $script:Helper = Join-Path $PSScriptRoot '..\..\packaging\windows\ftdi_driver.ps1'
    $script:HardwareId = 'USB\VID_0403&PID_601C'
    $script:Enumerated = @'
Published Name:     oem42.inf
Original Name:      ftdibus.inf
Provider Name:      FTDI
'@

    # The helper defines these; Pester can only mock commands that exist already.
    function Invoke-Pnputil([string]$exe, [string[]]$arguments) { throw 'not mocked' }
    function Invoke-Expand([string]$cabPath, [string]$dest) { throw 'not mocked' }

    function Invoke-Helper([string]$mode, [string]$cab = $script:Cab) {
        $result = Join-Path $TestDrive 'result.txt'
        & $script:Helper -Mode $mode -Cab $cab -Result $result
        return [pscustomobject]@{ Code = $LASTEXITCODE; Text = [IO.File]::ReadAllText($result) }
    }
}

Describe 'ftdi_driver.ps1' {
    BeforeEach {
        $script:ModulePath = $env:PSModulePath
        $script:Cab = Join-Path $TestDrive 'driver.cab'
        Set-Content -LiteralPath $script:Cab -Value 'fake cab'
        # Mock bodies run inside the helper script, where $script: is the helper's scope.
        $global:FtdiDriverFake = @{ Enumerated = $script:Enumerated; Cab = $script:Cab }
        $global:FtdiDriverFake.Package = @{
            'ftdibus.inf' = "[FtdiHw]`r`n%USB\VID_0403&PID_601C.DeviceDesc%=FtdiBus,$script:HardwareId`r`n"
            'ftdibus.cat' = 'fake catalog'
        }
        $global:FtdiDriverFake.Signature = [pscustomobject]@{
            Status            = 'Valid'
            SignerCertificate = [pscustomobject]@{ Subject = 'CN=Microsoft Windows Hardware Compatibility Publisher, O=Microsoft Corporation' }
        }
        $global:FtdiDriverFake.Store = ''
        $global:FtdiDriverFake.AddDriverExit = 0
        $global:FtdiDriverFake.AddDriverOutput = 'Driver package added successfully.'
        Mock Import-Module {} -ParameterFilter { "$Name" -like '*Microsoft.PowerShell.Security*' }
        Mock Get-AuthenticodeSignature { $global:FtdiDriverFake.Signature }
        Mock Invoke-Expand {
            foreach ($name in $global:FtdiDriverFake.Package.Keys) { Set-Content -LiteralPath (Join-Path $dest $name) -Value $global:FtdiDriverFake.Package[$name] }
        }
        Mock Invoke-Pnputil { $global:LASTEXITCODE = 0; $global:FtdiDriverFake.Store } -ParameterFilter { $arguments[0] -eq '/enum-drivers' }
        Mock Invoke-Pnputil {
            $global:LASTEXITCODE = $global:FtdiDriverFake.AddDriverExit
            if ($global:FtdiDriverFake.AddDriverExit -in 0, 259, 3010) { $global:FtdiDriverFake.Store = $global:FtdiDriverFake.Enumerated }
            $global:FtdiDriverFake.AddDriverOutput
        } -ParameterFilter { $arguments[0] -eq '/add-driver' }
    }
    AfterEach { $env:PSModulePath = $script:ModulePath }
    AfterAll { Remove-Variable -Name FtdiDriverFake -Scope Global -ErrorAction SilentlyContinue }

    Context 'Check' {
        It 'reports INSTALLED when ftdibus.inf is in the driver store' {
            $global:FtdiDriverFake.Store = $script:Enumerated
            $r = Invoke-Helper Check
            $r.Text | Should -BeExactly 'INSTALLED'
            $r.Code | Should -Be 0
        }

        It 'reports MISSING otherwise' {
            $global:FtdiDriverFake.Store = "Published Name: oem1.inf`r`nOriginal Name: other.inf`r`nOriginal Name: ftdibus.inf.bak"
            $r = Invoke-Helper Check
            $r.Text | Should -BeExactly 'MISSING'
            $r.Code | Should -Be 0
        }

        It 'runs pnputil from System32' {
            Invoke-Helper Check | Out-Null
            Should -Invoke Invoke-Pnputil -Times 1 -Exactly -ParameterFilter {
                $exe -eq (Join-Path $env:SystemRoot 'System32\pnputil.exe') -and $arguments.Count -eq 1
            }
        }

        It 'falls back to Sysnative when System32 has no pnputil (32-bit PowerShell)' {
            $root = $env:SystemRoot
            try {
                $env:SystemRoot = Join-Path $TestDrive 'Windows'
                Invoke-Helper Check | Out-Null
                Should -Invoke Invoke-Pnputil -Times 1 -Exactly -ParameterFilter {
                    $exe -eq (Join-Path $TestDrive 'Windows\Sysnative\pnputil.exe')
                }
            } finally { $env:SystemRoot = $root }
        }

        It 'needs no driver package' {
            $r = Invoke-Helper Check ''
            $r.Code | Should -Be 0
            Should -Invoke Invoke-Expand -Times 0 -Exactly
        }
    }

    Context 'Verify' {
        It 'accepts a signed package whose INF covers the FT4222H' {
            $r = Invoke-Helper Verify
            $r.Text | Should -BeExactly 'OK'
            $r.Code | Should -Be 0
            Should -Invoke Invoke-Expand -Times 1 -Exactly -ParameterFilter { $cabPath -eq $global:FtdiDriverFake.Cab }
            Should -Invoke Get-AuthenticodeSignature -Times 1 -Exactly -ParameterFilter { $LiteralPath -like '*ftdibus.cat' }
            Should -Invoke Invoke-Pnputil -Times 0 -Exactly
        }

        It 'reports a missing package (<label>)' -ForEach @(
            @{ label = 'no -Cab'; cab = '' }
            @{ label = 'no such file'; cab = 'C:\nowhere\driver.cab' }
        ) {
            $r = Invoke-Helper Verify $cab
            $r.Text | Should -BeExactly "ERROR: driver package not found: $cab"
            $r.Code | Should -Be 1
            Should -Invoke Invoke-Expand -Times 0 -Exactly
        }

        It 'reports <file> missing from the package' -ForEach @(
            @{ file = 'ftdibus.inf' }
            @{ file = 'ftdibus.cat' }
        ) {
            $global:FtdiDriverFake.Package.Remove($file)
            $r = Invoke-Helper Verify
            $r.Text | Should -BeExactly "ERROR: $file is missing from the driver package"
            $r.Code | Should -Be 1
        }

        It 'rejects a catalog whose signature is not valid' {
            $global:FtdiDriverFake.Signature.Status = 'NotSigned'
            $r = Invoke-Helper Verify
            $r.Text | Should -BeExactly 'ERROR: ftdibus.cat signature is not valid (NotSigned)'
            $r.Code | Should -Be 1
        }

        It 'rejects a catalog from the wrong signer' {
            $global:FtdiDriverFake.Signature.SignerCertificate.Subject = 'CN=FTDI Self-Signed'
            $r = Invoke-Helper Verify
            $r.Text | Should -BeExactly "ERROR: ftdibus.cat is signed by 'CN=FTDI Self-Signed', expected 'Microsoft Windows Hardware Compatibility Publisher'"
            $r.Code | Should -Be 1
        }

        It 'rejects an INF that does not list the FT4222H' {
            $global:FtdiDriverFake.Package['ftdibus.inf'] = "[FtdiHw]`r`nUSB\VID_0403&PID_6001`r`n"
            $r = Invoke-Helper Verify
            $r.Text | Should -BeExactly 'ERROR: ftdibus.inf does not list USB\VID_0403&PID_601C (FT4222H)'
            $r.Code | Should -Be 1
        }

        It 'removes its temporary folder' {
            $temp = [IO.Path]::GetTempPath()
            $before = @(Get-ChildItem -LiteralPath $temp -Directory -Filter 'n1mm-ftdidrv-*').Count
            Invoke-Helper Verify | Out-Null
            @(Get-ChildItem -LiteralPath $temp -Directory -Filter 'n1mm-ftdidrv-*').Count | Should -Be $before
        }
    }

    Context 'Install' {
        It 'adds and installs the verified INF (pnputil exit <exit>)' -ForEach @(
            @{ exit = 0 }, @{ exit = 259 }, @{ exit = 3010 }
        ) {
            $global:FtdiDriverFake.AddDriverExit = $exit
            $r = Invoke-Helper Install
            $r.Text | Should -BeExactly 'OK'
            $r.Code | Should -Be 0
            Should -Invoke Invoke-Pnputil -Times 1 -Exactly -ParameterFilter {
                $arguments.Count -eq 3 -and $arguments[0] -eq '/add-driver' -and
                $arguments[1] -like '*\n1mm-ftdidrv-*\ftdibus.inf' -and $arguments[2] -eq '/install'
            }
        }

        It 'does not run pnputil when verification fails' {
            $global:FtdiDriverFake.Signature.Status = 'HashMismatch'
            $r = Invoke-Helper Install
            $r.Text | Should -BeExactly 'ERROR: ftdibus.cat signature is not valid (HashMismatch)'
            Should -Invoke Invoke-Pnputil -Times 0 -Exactly
        }

        It 'reports a pnputil failure with its output on one line' {
            $global:FtdiDriverFake.AddDriverExit = 5
            $global:FtdiDriverFake.AddDriverOutput = "Adding driver package failed:`r`n  Access is denied.`r`n"
            $r = Invoke-Helper Install
            $r.Text | Should -BeExactly 'ERROR: pnputil /add-driver failed with exit code 5: Adding driver package failed: Access is denied.'
            $r.Code | Should -Be 1
        }

        It 'reports success that did not reach the driver store' {
            Mock Invoke-Pnputil { $global:LASTEXITCODE = 0; 'Driver package added successfully.' } -ParameterFilter { $arguments[0] -eq '/add-driver' }
            $r = Invoke-Helper Install
            $r.Text | Should -BeExactly 'ERROR: pnputil reported success (0) but ftdibus.inf is not in the driver store'
            $r.Code | Should -Be 1
        }

        It 'reports an unexpected exception' {
            Mock Get-AuthenticodeSignature { throw 'catalog unreadable' }
            $r = Invoke-Helper Install
            $r.Text | Should -BeExactly 'ERROR: catalog unreadable'
            $r.Code | Should -Be 1
        }
    }
}
