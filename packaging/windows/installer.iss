; SPDX-License-Identifier: GPL-3.0-only
; SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
;
; Inno Setup script for the N1MM Scope Bridge Windows installer (issue #20).
; Build with scripts/build_installer.py, which passes:
;   /DAppVersion=<x.y.z>  /DSourceDir=<PyInstaller one-folder app>  /DOutputDir=<dir>
;
; FTDI's LibFT4222 is proprietary and is never bundled (AGENTS.md rule 7). The
; installer only checks for it, offers FTDI's download page, and can copy the
; DLLs from a folder the user picks into the app folder. That is the user
; installing their own copy, not us distributing it.

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
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start {#AppName} when I sign in to &Windows"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

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
; DLLs the user chose to copy in from their own FTDI download.
Type: files; Name: "{app}\LibFT4222*.dll"
Type: files; Name: "{app}\ftd2xx.dll"

[Code]
var
  FtdiPage: TInputDirWizardPage;

function HasLibFT4222(Dir: String): Boolean;
begin
  Result := FileExists(AddBackslash(Dir) + 'LibFT4222-64.dll');
end;

procedure InitializeWizard();
begin
  FtdiPage := CreateInputDirPage(wpSelectTasks,
    'FTDI LibFT4222 library',
    'The FT-710''s scope is read through FTDI''s LibFT4222 library.',
    'FTDI''s license does not let us include LibFT4222, so download it from ' +
    'FTDI (' + '{#FtdiUrl}' + ') and unzip it. If you pick the unzipped folder ' +
    'below, setup copies LibFT4222-64.dll into the program folder for you. ' +
    'You can also leave this empty and set the folder later in the app.',
    False, '');
  FtdiPage.Add('Folder containing LibFT4222-64.dll (optional):');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = FtdiPage.ID) and HasLibFT4222(ExpandConstant('{sys}'));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: String;
  ErrorCode: Integer;
begin
  Result := True;
  if CurPageID = FtdiPage.ID then
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

procedure CurStepChanged(CurStep: TSetupStep);
var
  Dir: String;
begin
  if (CurStep = ssPostInstall) and not WizardSilent() then
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
