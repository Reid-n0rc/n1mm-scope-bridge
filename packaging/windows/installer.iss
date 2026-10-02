; SPDX-License-Identifier: GPL-3.0-only
; SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
;
; Inno Setup script for the N1MM Scope Bridge Windows installer (issues #20, #149).
; ONE installer for all Windows PCs. Build with scripts/build_installer.py, which passes:
;   /DAppVersion=<x.y.z>  /DOutputDir=<dir>
;   /DSourceX64=<x64 one-folder app>       (64-bit Windows; also Windows on ARM, emulated)
;   /DSourceArm64=<native ARM64 app>        (optional in development builds)
;   /DSourceX86=<32-bit command-line app>   (optional in development builds; no GUI)
;   /DFtdiWheelUrl /DFtdiWheelSha256 /DFtdiWheelFile /DFtdiLibSigner /DFtdiD2xxSigner
;   /DFtdiLicenceUrl, and with SourceX86 the same five with an "86" suffix
;   (from packaging/windows/ftdi_pin.json, the single source of truth)
;
; Payload choice at install time: 32-bit Windows gets the x86 command-line app;
; x64 Windows gets the x64 app; Windows on ARM gets the x64 app by default
; (FTDI's DLLs download automatically) or, on request, the native ARM64 app
; (FTDI's ARM64 DLLs must then be added by hand: there is no verifiable ARM64
; source to download from). /PAYLOAD=x64|arm64|x86 overrides the choice (tests).
;
; FTDI's LibFT4222 is proprietary and is never bundled (AGENTS.md rule 7). With
; the "ftdidownload" task (on by default) the user's installer downloads FTDI's
; signed DLLs for the chosen payload from the pinned URL at install time,
; verifies the SHA-256 and the Authenticode signatures (ftdi_install.ps1), and
; puts them in the program folder (#133). Otherwise the user can pick a folder
; they unzipped from FTDI. Either way the user obtains their own copy; we never
; distribute it.
; Silent installs: the download task is on by default and selecting it (or not
; deselecting it) accepts FTDI's licence terms; /MERGETASKS="!ftdidownload" skips it.

#ifndef AppVersion
  #error AppVersion must be defined (/DAppVersion=x.y.z)
#endif
#ifndef SourceX64
  #ifndef SourceArm64
    #ifndef SourceX86
      #error At least one payload is required: /DSourceX64, /DSourceArm64 or /DSourceX86
    #endif
  #endif
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

#define AppName "N1MM Scope Bridge"
#define GuiExe "N1MM Scope Bridge.exe"
#define CliExe "n1mm-scope-bridge.exe"
#define FtdiUrl "https://ftdichip.com/products/ft4222h/"
#define PrivacyUrl "https://reid-n0rc.github.io/n1mm-scope-bridge/privacy.html"
#ifndef FtdiWheelUrl
  #error FTDI pin defines missing; build with scripts/build_installer.py
#endif

[Setup]
AppId={{5B454E52-482B-4DB9-9888-C9C98FCD1306}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Reid Crowe, N0RC
AppPublisherURL=https://github.com/Reid-n0rc/n1mm-scope-bridge
AppSupportURL=https://github.com/Reid-n0rc/n1mm-scope-bridge/issues
AppUpdatesURL=https://github.com/Reid-n0rc/n1mm-scope-bridge/releases
VersionInfoVersion={#AppVersion}
VersionInfoCopyright=Copyright (C) 2026 Reid Crowe, N0RC. GPL-3.0-only.
; Per-user install by default (no admin needed); the dialog offers all users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
#ifdef SourceX86
; Every Windows PC: 32-bit Windows gets the command-line app.
ArchitecturesAllowed=x86compatible
#else
  #ifdef SourceX64
ArchitecturesAllowed=x64compatible
  #else
ArchitecturesAllowed=arm64
  #endif
#endif
; x64compatible also matches Windows 11 on ARM, so ARM PCs install in 64-bit mode.
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=n1mm-scope-bridge-setup-{#AppVersion}
; The command-line exe exists in every payload (the GUI is not in the 32-bit one).
UninstallDisplayIcon={app}\{#CliExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "ftdidownload"; Description: "&Download FTDI's LibFT4222 library from PyPI (needed for the Yaesu FT-710 scope)"; GroupDescription: "FTDI library:"; Check: CanDownloadFtdi
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Check: HasGui

[Files]
#ifdef SourceX64
Source: "{#SourceX64}\*"; DestDir: "{app}"; Check: IsPayload('x64'); Flags: ignoreversion recursesubdirs createallsubdirs
#endif
#ifdef SourceArm64
Source: "{#SourceArm64}\*"; DestDir: "{app}"; Check: IsPayload('arm64'); Flags: ignoreversion recursesubdirs createallsubdirs
#endif
#ifdef SourceX86
Source: "{#SourceX86}\*"; DestDir: "{app}"; Check: IsPayload('x86'); Flags: ignoreversion recursesubdirs createallsubdirs
; The 32-bit payload has no window: a console shortcut runs the bridge with the saved settings.
Source: "cli-start.cmd"; DestDir: "{app}"; Check: IsPayload('x86'); Flags: ignoreversion
#endif
; Helper only (extract + signature check); FTDI's DLLs themselves are downloaded.
Source: "ftdi_install.ps1"; Flags: dontcopy

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#GuiExe}"; Check: HasGui
Name: "{group}\{#AppName} (command line)"; Filename: "{app}\cli-start.cmd"; WorkingDir: "{app}"; Check: IsPayload('x86')
Name: "{group}\N1MM setup guide"; Filename: "https://reid-n0rc.github.io/n1mm-scope-bridge/"
Name: "{group}\Licenses"; Filename: "{app}\licenses"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#GuiExe}"; Tasks: desktopicon

[Registry]
; The program never starts with Windows (#136). Remove the Run value an earlier
; release candidate could create, on upgrade and on uninstall.
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "{#AppName}"; Flags: deletevalue uninsdeletevalue

[Run]
Filename: "{app}\{#GuiExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent; Check: HasGui

[UninstallDelete]
; FTDI DLLs downloaded by setup or copied in from the user's own FTDI download.
Type: files; Name: "{app}\LibFT4222*.dll"
Type: files; Name: "{app}\ftd2xx.dll"

[Code]
var
  Payload: String;
  ArchPage: TInputOptionWizardPage;
  X86Page: TOutputMsgWizardPage;
  FtdiPage: TInputQueryWizardPage;

function PayloadAvailable(P: String): Boolean;
begin
  Result := False;
#ifdef SourceX64
  // The x64 app runs on x64 Windows and, emulated, on Windows 11 on ARM.
  if P = 'x64' then Result := IsX64Compatible();
#endif
#ifdef SourceArm64
  if P = 'arm64' then Result := IsArm64();
#endif
#ifdef SourceX86
  if P = 'x86' then Result := True;
#endif
end;

function DefaultPayload(): String;
begin
  if IsArm64() and PayloadAvailable('x64') then
    Result := 'x64'  // FTDI's DLLs download automatically for the x64 app
  else if IsArm64() and PayloadAvailable('arm64') then
    Result := 'arm64'
  else if IsX64Compatible() and PayloadAvailable('x64') then
    Result := 'x64'
  else
    Result := 'x86';
end;

function IsPayload(P: String): Boolean;
begin
  Result := Payload = P;
end;

function HasGui(): Boolean;
begin
  Result := Payload <> 'x86';
end;

function LibName(): String;
begin
  if Payload = 'x86' then
    Result := 'LibFT4222.dll'
  else
    Result := 'LibFT4222-64.dll';
end;

function CanDownloadFtdi(): Boolean;
begin
  // There is no verifiable ARM64 FTDI download; the 32-bit pin is built in only with SourceX86.
  Result := (Payload = 'x64')
#ifdef SourceX86
    or (Payload = 'x86')
#endif
    ;
end;

function InitializeSetup(): Boolean;
begin
  Payload := Lowercase(ExpandConstant('{param:PAYLOAD|}'));
  if Payload = '' then
    Payload := DefaultPayload();
  Result := PayloadAvailable(Payload);
  if not Result then
    SuppressibleMsgBox('This installer has no "' + Payload + '" version of {#AppName} ' +
      'for this PC.', mbCriticalError, MB_OK, IDOK)
  else
    Log('Payload: ' + Payload);
end;

function HasLibFT4222(Dir: String): Boolean;
begin
  Result := FileExists(AddBackslash(Dir) + LibName());
end;

procedure BrowseClick(Sender: TObject);
var
  Dir: String;
begin
  Dir := FtdiPage.Values[0];
  if BrowseForFolder('Select the folder you unzipped from FTDI', Dir, False) then
    FtdiPage.Values[0] := Dir;
end;

procedure InitializeWizard();
var
  Browse: TNewButton;
begin
  ArchPage := CreateInputOptionPage(wpWelcome,
    'Choose a version', 'This PC runs Windows on ARM.',
    'Both versions work. The x64 version runs under Windows'' built-in x64 emulation, ' +
    'and setup can download FTDI''s library for it. The native ARM64 version is faster, ' +
    'but you must add FTDI''s ARM64 LibFT4222-64.dll and ftd2xx.dll from FTDI''s ' +
    'LibFT4222 package yourself.', True, False);
  ArchPage.Add('x64 version (recommended): FTDI''s library is downloaded for you');
  ArchPage.Add('Native ARM64 version: add FTDI''s ARM64 DLLs yourself');
  ArchPage.SelectedValueIndex := 0;

  X86Page := CreateOutputMsgPage(wpWelcome,
    'Command-line version', 'This PC runs 32-bit Windows.',
    'The {#AppName} window (GUI) needs 64-bit Windows, so this PC gets the command-line ' +
    'version. It does the same job: it streams your Yaesu radio''s scope to N1MM+.' + #13#10#13#10 +
    'After installing, use the Start menu shortcut "{#AppName} (command ' +
    'line)". It runs the bridge with your saved settings; see the user guide for the ' +
    'options (n1mm-scope-bridge run --help).');

  // A plain text field (optional): TInputDirWizardPage rejects an empty path.
  FtdiPage := CreateInputQueryPage(wpSelectTasks,
    'FTDI LibFT4222 library',
    'The FT-710''s scope is read through FTDI''s LibFT4222 library.',
    'FTDI''s license does not let us include LibFT4222, so download it from ' +
    'FTDI (' + '{#FtdiUrl}' + ') and unzip it. If you pick the unzipped folder ' +
    'below, setup copies the DLLs for this PC into the program folder for you. ' +
    'You can also leave this empty and set the folder later in the app.');
  FtdiPage.Add('Folder containing FTDI''s LibFT4222 DLLs (optional):', False);
  Browse := TNewButton.Create(FtdiPage);
  Browse.Parent := FtdiPage.Surface;
  Browse.Caption := '&Browse...';
  Browse.Width := ScaleX(90);
  Browse.Height := ScaleY(23);
  Browse.Left := FtdiPage.SurfaceWidth - Browse.Width;
  Browse.Top := FtdiPage.Edits[0].Top + FtdiPage.Edits[0].Height + ScaleY(8);
  Browse.OnClick := @BrowseClick;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = ArchPage.ID then
    // Only on Windows on ARM, when both versions are in this installer and /PAYLOAD wasn't given.
    Result := WizardSilent() or not IsArm64() or not PayloadAvailable('x64') or
      not PayloadAvailable('arm64') or (ExpandConstant('{param:PAYLOAD|}') <> '')
  else if PageID = X86Page.ID then
    Result := WizardSilent() or (Payload <> 'x86')
  else if PageID = FtdiPage.ID then
    // Silent installs never ask; the GUI checks for LibFT4222 at launch.
    Result := WizardSilent() or WizardIsTaskSelected('ftdidownload')
      or HasLibFT4222(ExpandConstant('{sys}'));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: String;
  ErrorCode: Integer;
begin
  Result := True;
  if CurPageID = ArchPage.ID then
  begin
    if ArchPage.SelectedValueIndex = 1 then
      Payload := 'arm64'
    else
      Payload := 'x64';
    Log('Payload chosen on the version page: ' + Payload);
  end
  // Silent installs: choosing the ftdidownload task (the default) is the acceptance;
  // a plain MsgBox here would block a silent install on an invisible dialog.
  else if (CurPageID = wpSelectTasks) and WizardIsTaskSelected('ftdidownload') and not WizardSilent() then
  begin
    Result := MsgBox('Setup will download FTDI''s LibFT4222 and D2XX libraries from ' +
      'the Python Package Index (PyPI, run by the Python Software Foundation): the ' +
      'ft4222 package, which redistributes FTDI''s unmodified, signed DLLs. Setup checks ' +
      'them and puts them in the program folder.' + #13#10#13#10 +
      'Privacy: like any download, this request shows PyPI your IP address. Nothing else ' +
      'is sent. See the privacy notice: {#PrivacyUrl}' + #13#10#13#10 +
      'FTDI licence terms (summary): FTDI drivers may be used only in conjunction with ' +
      'products based on FTDI parts (the FT-710 uses FTDI''s FT4222H). The software is ' +
      'provided "as is" without warranty. Full terms: {#FtdiLicenceUrl}' + #13#10#13#10 +
      'Do you accept FTDI''s licence terms and want setup to download the library?',
      mbConfirmation, MB_YESNO) = IDYES;
    if not Result then
      MsgBox('Untick "Download FTDI''s LibFT4222 library" to continue without it. ' +
        'You can then pick a folder you downloaded from FTDI yourself.', mbInformation, MB_OK);
  end
  else if CurPageID = FtdiPage.ID then
  begin
    Dir := Trim(FtdiPage.Values[0]);
    if (Dir <> '') and not HasLibFT4222(Dir) then
    begin
      MsgBox(LibName() + ' was not found in that folder. Pick the folder with FTDI''s ' +
        'DLLs for this PC, or leave the box empty.', mbError, MB_OK);
      Result := False;
    end
    else if Dir = '' then
    begin
      if MsgBox('Open FTDI''s LibFT4222 download page now?', mbConfirmation,
        MB_YESNO) = IDYES then
        ShellExec('open', '{#FtdiUrl}', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
    end;
  end;
end;

procedure FtdiDownloadFailed(Reason: String);
begin
  Log('FTDI download: ' + Reason);
  if not WizardSilent() then
    MsgBox('N1MM Scope Bridge is installed, but setup could not get FTDI''s LibFT4222 ' +
      'library:' + #13#10 + Reason + #13#10#13#10 +
      'Download it from FTDI ({#FtdiUrl}) and set the FTDI library folder in the app''s ' +
      'Settings, or run setup again later.', mbError, MB_OK);
end;

procedure DownloadFtdi();
var
  Url, Sha256, WheelFile, LibSigner, D2xxSigner: String;
  Wheel, Helper, ResultFile, Params: String;
  Code: Integer;
  Message: AnsiString;
begin
  Url := '{#FtdiWheelUrl}';
  Sha256 := '{#FtdiWheelSha256}';
  WheelFile := '{#FtdiWheelFile}';
  LibSigner := '{#FtdiLibSigner}';
  D2xxSigner := '{#FtdiD2xxSigner}';
#ifdef SourceX86
  if Payload = 'x86' then
  begin
    Url := '{#FtdiWheelUrl86}';
    Sha256 := '{#FtdiWheelSha25686}';
    WheelFile := '{#FtdiWheelFile86}';
    LibSigner := '{#FtdiLibSigner86}';
    D2xxSigner := '{#FtdiD2xxSigner86}';
  end;
#endif
  Log('FTDI download: fetching ' + Url);
  try
    DownloadTemporaryFile(Url, WheelFile, Sha256, nil);
  except
    FtdiDownloadFailed('download failed: ' + GetExceptionMessage());
    exit;
  end;
  Log('FTDI download: SHA-256 verified; extracting and checking signatures');
  ExtractTemporaryFile('ftdi_install.ps1');
  Wheel := ExpandConstant('{tmp}\') + WheelFile;
  Helper := ExpandConstant('{tmp}\ftdi_install.ps1');
  ResultFile := ExpandConstant('{tmp}\ftdi_result.txt');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + Helper + '" -Wheel "' + Wheel +
    '" -Dest "' + ExpandConstant('{app}') + '" -LibName "' + LibName() + '" -LibSigner "' +
    LibSigner + '" -D2xxSigner "' + D2xxSigner + '" -Result "' + ResultFile + '"';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '',
    SW_HIDE, ewWaitUntilTerminated, Code) then
  begin
    FtdiDownloadFailed('could not run PowerShell: ' + SysErrorMessage(Code));
    exit;
  end;
  Log('FTDI download: helper exited with code ' + IntToStr(Code));
  if not LoadStringFromFile(ResultFile, Message) then
    Message := 'ERROR: no result from the FTDI helper';
  if (Code <> 0) or (Pos('OK', Trim(String(Message))) <> 1) then
    FtdiDownloadFailed(Trim(String(Message)))
  else
    Log('FTDI download: ' + LibName() + ' and ftd2xx.dll installed and signature-verified');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Dir: String;
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('ftdidownload') then
    DownloadFtdi()
  else if (CurStep = ssPostInstall) and not WizardSilent() then
  begin
    Dir := Trim(FtdiPage.Values[0]);
    if (Dir <> '') and HasLibFT4222(Dir) then
    begin
      FileCopy(AddBackslash(Dir) + LibName(), ExpandConstant('{app}\') + LibName(), False);
      if FileExists(AddBackslash(Dir) + 'ftd2xx.dll') then
        FileCopy(AddBackslash(Dir) + 'ftd2xx.dll', ExpandConstant('{app}\ftd2xx.dll'), False);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  SettingsDir: String;
begin
  // Settings are kept unless the user asks to remove them (never in silent mode).
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent() then
  begin
    SettingsDir := ExpandConstant('{userappdata}\n1mm-scope-bridge');
    if DirExists(SettingsDir) and (MsgBox('Also remove your N1MM Scope Bridge settings?',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(SettingsDir, True, True, True);
  end;
end;
