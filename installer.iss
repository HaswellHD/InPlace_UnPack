; Inno Setup 6 script - compile with ISCC.exe installer.iss (build.ps1 does it if installed)
; Per-user install: no admin rights needed.
#define AppName "Inplace-Unpack"
#define AppVersion "0.4.0"
#define AppExe "Inplace-Unpack.exe"

[Setup]
AppId={{6F1C2A57-3E1B-4F0E-9B7C-2D3A9E7F1B44}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=EZG_Haswell
DefaultDirName={localappdata}\Programs\Inplace-Unpack
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=Inplace-Unpack-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=LICENSE
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "explorermenu"; Description: "Add ""Extract with Inplace-Unpack"" to the right-click menu of .zip / .zip.001 files"

[Registry]
; per user (HKCU), no admin rights; removed on uninstall. Windows 11: under "Show more options".
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\InplaceUnpack"; ValueType: string; ValueName: ""; ValueData: "Extract with Inplace-Unpack"; Tasks: explorermenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\InplaceUnpack"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.zip\shell\InplaceUnpack\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.001\shell\InplaceUnpack"; ValueType: string; ValueName: ""; ValueData: "Extract with Inplace-Unpack"; Tasks: explorermenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.001\shell\InplaceUnpack"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.001\shell\InplaceUnpack\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: explorermenu

[Files]
Source: "dist\Inplace-Unpack.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\inplace-unpack-cli.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; remove the optional "resume after reboot" autostart entry
Filename: "reg.exe"; Parameters: "delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v Inplace-Unpack-Resume /f"; Flags: runhidden; RunOnceId: "RemoveAutostart"
