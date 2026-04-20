; PharmAuto Inno Setup 설치 스크립트 (Nuitka 빌드용)
; 빌드: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

#define MyAppName "PharmAuto"
#define MyAppVersion "1.5.35"
#define MyAppPublisher "PharmAuto"
#define MyAppExeName "PharmAuto.exe"
#define BuildDir "dist_nuitka\main.dist"

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
SetupIconFile=ui\icons\pharmauto.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=PharmAuto.exe
RestartApplications=yes
PrivilegesRequired=admin

; 설치 화면 한글
[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "startup"; Description: "Windows 시작 시 자동 실행"; GroupDescription: "추가 옵션:"

[Files]
; Nuitka 빌드 결과 — 플랫 구조 (exe + dll/pyd + 서브폴더 전부)
; v1.5.35 부터 사용자 데이터는 {userappdata}\PharmAuto 에만 저장 — {app} 은 바이너리 전용
Source: "{#BuildDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\*"; DestDir: "{app}"; Excludes: "{#MyAppExeName},config\*,data\*,screenshots\*"; Flags: ignoreversion recursesubdirs createallsubdirs
; tools: 유팜 SQL 자동 설정용 스크립트 + PsExec
Source: "tools\setup_upharm_sql.bat"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "tools\psexec64.exe"; DestDir: "{app}\tools"; Flags: ignoreversion

[Icons]
; 시작 메뉴
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} 제거"; Filename: "{uninstallexe}"; IconFilename: "{app}\{#MyAppExeName}"
; 바탕화면 — 항상 생성 (사용자가 앱 위치 쉽게 찾을 수 있도록)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"

[Registry]
; Windows 시작 시 자동 실행 등록
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "PharmAuto 실행"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; 업데이트 시 옛날 PyInstaller 잔재 정리
Type: filesandordirs; Name: "{app}\_internal"
; v1.5.35: 구 버전이 남긴 {app}\config, {app}\data 비우기 — 앱이 첫 실행 시 APPDATA 로 자동 이전
; (migrate_from_legacy_install 이 이전 끝나고 여기서 지워야 함 — 순서: 앱 기동 전 InstallDelete)
; 주의: InstallDelete 는 파일 복사 전에 실행되므로, 마이그레이션은 앱 기동 시 이루어진다.
; 따라서 여기서는 config 를 아직 지우지 않음 (첫 기동 마이그레이션이 먼저).
; 대신 앱 실행 시 paths.migrate_from_legacy_install() 완료 후 사용자가 다음 업데이트 때 정리됨.
; Nuitka 모듈 폴더 갱신
Type: filesandordirs; Name: "{app}\PyQt6"
Type: filesandordirs; Name: "{app}\playwright"
Type: filesandordirs; Name: "{app}\playwright_browsers"
Type: filesandordirs; Name: "{app}\certifi"
Type: filesandordirs; Name: "{app}\ui"
Type: files; Name: "{app}\PharmAuto.exe"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { 파일 복사 전에 Defender 예외 등록 (코드 서명 도입 시 제거) }
  { 관리자 권한으로 실행되므로 직접 호출 가능 }
  Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -Command "Add-MpPreference -ExclusionPath ''' + ExpandConstant('{app}') + '''"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    WizardForm.StatusLabel.Visible := False;
    WizardForm.FilenameLabel.Visible := False;
  end;
end;
