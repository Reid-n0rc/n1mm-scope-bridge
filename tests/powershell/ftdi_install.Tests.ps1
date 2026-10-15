# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
#
# packaging/windows/ftdi_install.ps1 (#133, #149) against fake wheels, with
# Get-AuthenticodeSignature mocked. No FTDI files are used (#181).

BeforeAll {
    $script:Helper = Join-Path $PSScriptRoot '..\..\packaging\windows\ftdi_install.ps1'
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem

    function New-Wheel([string[]]$entries) {
        $path = Join-Path $TestDrive ("wheel-" + [guid]::NewGuid().ToString('N') + '.whl')
        $zip = [IO.Compression.ZipFile]::Open($path, 'Create')
        try {
            foreach ($entry in $entries) {
                $writer = [IO.StreamWriter]::new($zip.CreateEntry($entry).Open())
                $writer.Write("fake $entry"); $writer.Dispose()
            }
        } finally { $zip.Dispose() }
        return $path
    }

    function Invoke-Helper([string]$wheel, [string]$libName = 'LibFT4222-64.dll') {
        $result = Join-Path $TestDrive 'result.txt'
        & $script:Helper -Wheel $wheel -Dest $script:Dest -LibName $libName `
            -LibSigner 'Future Technology Devices International' `
            -D2xxSigner 'Microsoft Windows Hardware Compatibility' -Result $result
        return [pscustomobject]@{ Code = $LASTEXITCODE; Text = [IO.File]::ReadAllText($result) }
    }

    $script:Subjects = @{
        'LibFT4222-64.dll' = 'CN=Future Technology Devices International Ltd, O=Future Technology Devices International Ltd'
        'LibFT4222.dll'    = 'CN=Future Technology Devices International Ltd, O=Future Technology Devices International Ltd'
        'ftd2xx.dll'       = 'CN=Microsoft Windows Hardware Compatibility Publisher, O=Microsoft Corporation'
    }
}

Describe 'ftdi_install.ps1' {
    BeforeEach {
        $script:ModulePath = $env:PSModulePath
        $script:Dest = Join-Path $TestDrive ("app-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $script:Dest | Out-Null
        # Mock bodies run inside the helper script, where $script: is the helper's scope.
        $global:FtdiInstallFake = @{ Status = @{}; Signers = $script:Subjects.Clone() }
        Mock Import-Module {} -ParameterFilter { "$Name" -like '*Microsoft.PowerShell.Security*' }
        Mock Get-AuthenticodeSignature {
            $leaf = Split-Path $LiteralPath -Leaf
            $fake = $global:FtdiInstallFake
            $status = if ($fake.Status.ContainsKey($leaf)) { $fake.Status[$leaf] } else { 'Valid' }
            [pscustomobject]@{ Status = $status; SignerCertificate = [pscustomobject]@{ Subject = $fake.Signers[$leaf] } }
        }
    }
    AfterEach { $env:PSModulePath = $script:ModulePath }
    AfterAll { Remove-Variable -Name FtdiInstallFake -Scope Global -ErrorAction SilentlyContinue }

    It 'installs both signed DLLs for the 64-bit app' {
        $r = Invoke-Helper (New-Wheel 'ft4222/libs/LibFT4222-64.dll', 'ft4222/libs/ftd2xx.dll', 'ft4222/__init__.py')
        $r.Text | Should -BeExactly 'OK'
        $r.Code | Should -Be 0
        Join-Path $script:Dest 'LibFT4222-64.dll' | Should -Exist
        Join-Path $script:Dest 'ftd2xx.dll' | Should -Exist
        Should -Invoke Get-AuthenticodeSignature -Times 2 -Exactly
    }

    It 'installs the 32-bit library for the x86 app' {
        $r = Invoke-Helper (New-Wheel 'libs/LibFT4222.dll', 'libs/ftd2xx.dll') 'LibFT4222.dll'
        $r.Text | Should -BeExactly 'OK'
        Join-Path $script:Dest 'LibFT4222.dll' | Should -Exist
        Join-Path $script:Dest 'LibFT4222-64.dll' | Should -Not -Exist
    }

    It 'matches entries with Windows path separators' {
        $r = Invoke-Helper (New-Wheel 'libs\LibFT4222-64.dll', 'libs\ftd2xx.dll')
        $r.Text | Should -BeExactly 'OK'
    }

    It 'does not match a file whose name only ends with the DLL name' {
        $r = Invoke-Helper (New-Wheel 'libs/LibFT4222-64.dll', 'libs/notftd2xx.dll')
        $r.Text | Should -BeExactly 'ERROR: expected one ftd2xx.dll in the download, found 0'
        $r.Code | Should -Be 1
    }

    It 'rejects a wheel with two copies of a DLL' {
        $r = Invoke-Helper (New-Wheel 'a/LibFT4222-64.dll', 'b/LibFT4222-64.dll', 'a/ftd2xx.dll')
        $r.Text | Should -BeExactly 'ERROR: expected one LibFT4222-64.dll in the download, found 2'
        $r.Code | Should -Be 1
    }

    It 'rejects a DLL whose signature is not valid' {
        $global:FtdiInstallFake.Status['ftd2xx.dll'] = 'HashMismatch'
        $r = Invoke-Helper (New-Wheel 'libs/LibFT4222-64.dll', 'libs/ftd2xx.dll')
        $r.Text | Should -BeExactly 'ERROR: ftd2xx.dll signature is not valid (HashMismatch)'
        $r.Code | Should -Be 1
        Join-Path $script:Dest 'ftd2xx.dll' | Should -Not -Exist
        Join-Path $script:Dest 'LibFT4222-64.dll' | Should -Not -Exist
    }

    It 'rejects a valid signature from the wrong signer' {
        $global:FtdiInstallFake.Signers['LibFT4222-64.dll'] = 'CN=Someone Else'
        $r = Invoke-Helper (New-Wheel 'libs/LibFT4222-64.dll', 'libs/ftd2xx.dll')
        $r.Text | Should -BeExactly "ERROR: LibFT4222-64.dll is signed by 'CN=Someone Else', expected 'Future Technology Devices International'"
        $r.Code | Should -Be 1
    }

    It 'reports an unreadable download as an error' {
        $r = Invoke-Helper (Join-Path $TestDrive 'missing.whl')
        $r.Text | Should -BeLike 'ERROR: *'
        $r.Code | Should -Be 1
    }

    It 'reports a copy failure as an error' {
        $wheel = New-Wheel 'libs/LibFT4222-64.dll', 'libs/ftd2xx.dll'
        Remove-Item -LiteralPath $script:Dest
        $r = Invoke-Helper $wheel
        $r.Text | Should -BeLike 'ERROR: *'
        $r.Code | Should -Be 1
    }

    It 'removes its temporary folder' {
        $temp = [IO.Path]::GetTempPath()
        $before = @(Get-ChildItem -LiteralPath $temp -Directory -Filter 'n1mm-ftdi-*').Count
        Invoke-Helper (New-Wheel 'libs/LibFT4222-64.dll', 'libs/ftd2xx.dll') | Out-Null
        Invoke-Helper (New-Wheel 'libs/LibFT4222-64.dll') | Out-Null
        @(Get-ChildItem -LiteralPath $temp -Directory -Filter 'n1mm-ftdi-*').Count | Should -Be $before
    }

    It 'writes the result as ASCII without a byte-order mark' {
        Invoke-Helper (New-Wheel 'libs/LibFT4222-64.dll', 'libs/ftd2xx.dll') | Out-Null
        [IO.File]::ReadAllBytes((Join-Path $TestDrive 'result.txt')) | Should -Be ([byte[]][char[]]'OK')
    }
}
