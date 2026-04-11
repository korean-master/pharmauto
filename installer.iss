; PharmAuto Inno Setup 설치 스크립트
; 빌드: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

#define MyAppName "PharmAuto"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "PharmAuto"
#define MyAppExeName "PharmAuto.exe"

[Setup]
AppId={{B8A7F3E2-4D5C-6E7F-8A9B-0C1D2E3F4A5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=PharmAutoSetup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 설치 화면 한글
[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 생성"; GroupDescription: "추가 옵션:"

[Files]
; dist/PharmAuto 폴더 전체를 설치 경로에 복사
Source: "dist\PharmAuto\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\PharmAuto\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; config 폴더는 빈 초기 파일만 (사용자 데이터 보호)
Source: "dist\PharmAuto\_internal\config\*"; DestDir: "{app}\_internal\config"; Flags: onlyifdoesntexist recursesubdirs

[Dirs]
Name: "{app}\_internal\data"; Permissions: users-full
Name: "{app}\_internal\config"; Permissions: users-full
Name: "{app}\_internal\config\selectors"; Permissions: users-full
Name: "{app}\_internal\screenshots"; Permissions: users-full

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "PharmAuto 실행"; Flags: nowait postinstall skipifsilent
