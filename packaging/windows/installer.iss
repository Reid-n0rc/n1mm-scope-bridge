; SPDX-License-Identifier: GPL-3.0-only
; SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
;
; Inno Setup script for the N1MM Scope Bridge Windows installer (issue #20).
; Build with scripts/build_installer.py, which passes:
;   /DAppVersion=<x.y.z>  /DSourceDir=<PyInstaller one-folder app>  /DOutputDir=<dir>
;   /DFtdiWheelUrl /DFtdiWheelSha256 /DFtdiWheelFile /DFtdiLibSigner /DFtdiD2xxSigner
;   /DFtdiLicenceUrl  (from packaging/windows/ftdi_pin.json, the single source of truth)
;
; FTDI's LibFT4222 is proprietary and is never bundled (AGENTS.md rule 7). With
; the "ftdidownload" task (on by default) the user's installer downloads FTDI's
; signed DLLs from the pinned URL at install time, verifies the SHA-256 and the
; Authenticode signatures (ftdi_install.ps1), and puts them in the program
; folder (#133). Otherwise the user can pick a folder they unzipped from FTDI.
; Either way the user obtains their own copy; we never distribute it.
; Silent installs: /MERGETASKS="!ftdidownload" skips the download.

#ifndef AppVersion
  #error AppVersion must be defined (/DAppVersion=x.y.z)
#endif
#ifndef SourceDir
  #error SourceDir must be defined (/DSourceDir=path to the one-folder app)
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

#define AppName "N1MM Scope Bridge"
#define GuiExe "N1MM Scope Bridge.exe"
#define CliExe "n1mm-scope-bridge.exe"
#define FtdiUrl "https://ftdichip.com/products/ft4222h/"
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
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=n1mm-scope-bridge-setup-{#AppVersion}
UninstallDisplayIcon={app}\{#GuiExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "ftdidownload"; Description: "&Download FTDI's LibFT4222 library (needed for the Yaesu FT-710 scope)"; GroupDescription: "FTDI library:"
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start {#AppName} when I sign in to &Windows"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Helper only (extract + signature check); FTDI's DLLs themselves are downloaded.
Source: "ftdi_install.ps1"; Flags: dontcopy

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#GuiExe}"
Name: "{group}\N1MM setup guide"; Filename: "https://reid-n0rc.github.io/n1mm-scope-bridge/"
Name: "{group}\Licenses"; Filename: "{app}\licenses"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#GuiExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#GuiExe}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#GuiExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; FTDI DLLs downloaded by setup or copied in from the user's own FTDI download.
Type: files; Name: "{app}\LibFT4222*.dll"
Type: files; Name: "{app}\ftd2xx.dll"

[Code]
var
  FtdiPage: TInputQueryWizardPage;

function HasLibFT4222(Dir: String): Boolean;
begin
  Result := FileExists(AddBackslash(Dir) + 'LibFT4222-64.dll');
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
  // A plain text field (optional): TInputDirWizardPage rejects an empty path.
  FtdiPage := CreateInputQueryPage(wpSelectTasks,
    'FTDI LibFT4222 library',
    'The FT-710''s scope is read through FTDI''s LibFT4222 library.',
    'FTDI''s license does not let us include LibFT4222, so download it from ' +
    'FTDI (' + '{#FtdiUrl}' + ') and unzip it. If you pick the unzipped folder ' +
    'below, setup copies LibFT4222-64.dll into the program folder for you. ' +
    'You can also leave this empty and set the folder later in the app.');
  FtdiPage.Add('Folder containing LibFT4222-64.dll (optional):', False);
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
  // Silent installs never ask; the GUI checks for LibFT4222 at launch.
  Result := (PageID = FtdiPage.ID) and (WizardSilent() or WizardIsTaskSelected('ftdidownload')
    or HasLibFT4222(ExpandConstant('{sys}')));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: String;
  ErrorCode: Integer;
begin
  Result := True;
  if (CurPageID = wpSelectTasks) and WizardIsTaskSelected('ftdidownload') then
  begin
    Result := MsgBox('Setup will download FTDI''s LibFT4222 and D2XX libraries from ' +
      'PyPI (the ft4222 package, which redistributes FTDI''s unmodified, signed DLLs), ' +
      'check them, and put them in the program folder.' + #13#10#13#10 +
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
      MsgBox('LibFT4222-64.dll was not found in that folder. Pick the folder ' +
        'you unzipped from FTDI, or leave the box empty.', mbError, MB_OK);
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
  Wheel, Helper, ResultFile, Params: String;
  Code: Integer;
  Message: AnsiString;
begin
  try
    DownloadTemporaryFile('{#FtdiWheelUrl}', '{#FtdiWheelFile}', '{#FtdiWheelSha256}', nil);
  except
    FtdiDownloadFailed('download failed: ' + GetExceptionMessage());
    exit;
  end;
  ExtractTemporaryFile('ftdi_install.ps1');
  Wheel := ExpandConstant('{tmp}\{#FtdiWheelFile}');
  Helper := ExpandConstant('{tmp}\ftdi_install.ps1');
  ResultFile := ExpandConstant('{tmp}\ftdi_result.txt');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + Helper + '" -Wheel "' + Wheel +
    '" -Dest "' + ExpandConstant('{app}') + '" -LibSigner "{#FtdiLibSigner}"' +
    ' -D2xxSigner "{#FtdiD2xxSigner}" -Result "' + ResultFile + '"';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '',
    SW_HIDE, ewWaitUntilTerminated, Code) then
  begin
    FtdiDownloadFailed('could not run PowerShell: ' + SysErrorMessage(Code));
    exit;
  end;
  if not LoadStringFromFile(ResultFile, Message) then
    Message := 'ERROR: no result from the FTDI helper';
  if (Code <> 0) or (Trim(String(Message)) <> 'OK') then
    FtdiDownloadFailed(Trim(String(Message)))
  else
    Log('FTDI download: LibFT4222-64.dll and ftd2xx.dll installed and signature-verified');
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
      FileCopy(AddBackslash(Dir) + 'LibFT4222-64.dll', ExpandConstant('{app}\LibFT4222-64.dll'), False);
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
