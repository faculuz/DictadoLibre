#ifndef MyVersion
  #define MyVersion "1.3.0"
#endif
[Setup]
AppId={{7D3A6B2E-5C1F-4E8A-9B7D-1F2E3A4B5C6D}
AppName=Dictado Libre
AppVersion={#MyVersion}
AppPublisher=Facundo Luzardo
DefaultDirName={localappdata}\Programs\DictadoLibre
DefaultGroupName=Dictado Libre
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=DictadoLibre-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\DictadoLibre.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=DictadoLibreMutex
CloseApplications=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"
Name: "autostart"; Description: "Iniciar Dictado Libre con Windows"

[Files]
Source: "dist\DictadoLibre\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Dictado Libre"; Filename: "{app}\DictadoLibre.exe"; AppUserModelID: "FacundoLuzardo.DictadoLibre"
Name: "{autodesktop}\Dictado Libre"; Filename: "{app}\DictadoLibre.exe"; AppUserModelID: "FacundoLuzardo.DictadoLibre"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DictadoLibre"; ValueData: """{app}\DictadoLibre.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\DictadoLibre.exe"; Description: "Abrir Dictado Libre"; Flags: nowait postinstall skipifsilent
Filename: "{app}\DictadoLibre.exe"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM DictadoLibre.exe"; Flags: runhidden; RunOnceId: "KillApp"
