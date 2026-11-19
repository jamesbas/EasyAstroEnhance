[Setup]
AppId={{CE3A36C8-1F67-4D05-B6D1-62CA0A76D073}
AppName=EasyAstroEnhance
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\EasyAstroEnhance
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.22000
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputBaseFilename=EasyAstroEnhance-{#AppVersion}-Windows-x64-Setup
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Excludes: "*.pyc,*\__pycache__\*"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{userprograms}\EasyAstroEnhance"; Filename: "{app}\launch.cmd"; WorkingDir: "{app}"
Name: "{userdesktop}\EasyAstroEnhance"; Filename: "{app}\launch.cmd"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\launch.cmd"; WorkingDir: "{app}"; Description: "Open EasyAstroEnhance"; Flags: shellexec nowait postinstall skipifsilent
