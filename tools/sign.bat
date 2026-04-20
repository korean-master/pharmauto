@echo off
:: tools/sign.bat — PharmAuto EV 코드사이닝 래퍼
::
:: 사용법:
::   tools\sign.bat <exe_path>
::
:: 환경변수:
::   PHARMAUTO_SIGN_SKIP=1        → 서명 생략 (인증서 도착 전 개발 빌드)
::   PHARMAUTO_SIGN_TOOL=esigner  → SSL.com eSigner CodeSignTool 사용 (기본)
::   PHARMAUTO_SIGN_TOOL=signtool → Windows signtool.exe + PFX 사용 (폴백)
::
:: [esigner 모드 — 인증서 도착 후 세팅]
::   CODESIGNTOOL_PATH        : CodeSignTool 설치 경로 (CodeSignTool.bat 포함 폴더)
::   ESIGNER_CREDENTIAL_ID    : SSL.com 콘솔에서 발급받은 credential ID
::   ESIGNER_USERNAME         : SSL.com 로그인 이메일
::   ESIGNER_PASSWORD         : SSL.com 로그인 비밀번호
::   ESIGNER_TOTP_SECRET      : SSL.com 에서 받은 TOTP base32 시크릿 (TOTP 코드 아님!)
::
:: [signtool 모드]
::   SIGNTOOL_PATH            : signtool.exe 경로 (기본: PATH 에서 찾음)
::   PHARMAUTO_CERT_PATH      : .pfx 파일 경로
::   PHARMAUTO_CERT_PW        : PFX 비밀번호

setlocal enabledelayedexpansion

set FILE=%~1
if "%FILE%"=="" (
  echo [sign] ERROR: 파일 경로 인자 필요 — 사용법: sign.bat ^<exe_path^>
  exit /b 1
)
if not exist "%FILE%" (
  echo [sign] ERROR: 파일 없음 — %FILE%
  exit /b 1
)

if "%PHARMAUTO_SIGN_SKIP%"=="1" (
  echo [sign] SKIP ^(PHARMAUTO_SIGN_SKIP=1^) — %FILE%
  exit /b 0
)

if "%PHARMAUTO_SIGN_TOOL%"=="" set PHARMAUTO_SIGN_TOOL=esigner

if /I "%PHARMAUTO_SIGN_TOOL%"=="esigner"  goto :sign_esigner
if /I "%PHARMAUTO_SIGN_TOOL%"=="signtool" goto :sign_signtool

echo [sign] ERROR: 알 수 없는 PHARMAUTO_SIGN_TOOL — %PHARMAUTO_SIGN_TOOL%
exit /b 1

:sign_esigner
if "%CODESIGNTOOL_PATH%"=="" (
  echo [sign] ERROR: CODESIGNTOOL_PATH 미설정 — SSL.com CodeSignTool 설치 후 설정 필요
  exit /b 1
)
if not exist "%CODESIGNTOOL_PATH%\CodeSignTool.bat" (
  echo [sign] ERROR: CodeSignTool.bat 없음 — %CODESIGNTOOL_PATH%
  exit /b 1
)
for %%V in (ESIGNER_CREDENTIAL_ID ESIGNER_USERNAME ESIGNER_PASSWORD ESIGNER_TOTP_SECRET) do (
  if "!%%V!"=="" (
    echo [sign] ERROR: %%V 환경변수 미설정
    exit /b 1
  )
)

echo [sign] eSigner 서명 중 — %FILE%
pushd "%CODESIGNTOOL_PATH%"
call CodeSignTool.bat sign ^
  -credential_id=%ESIGNER_CREDENTIAL_ID% ^
  -username=%ESIGNER_USERNAME% ^
  -password=%ESIGNER_PASSWORD% ^
  -totp_secret=%ESIGNER_TOTP_SECRET% ^
  -input_file_path="%FILE%" ^
  -override=true
set RC=%errorlevel%
popd
if not "%RC%"=="0" (
  echo [sign] ERROR: eSigner 서명 실패 ^(rc=%RC%^)
  exit /b %RC%
)
goto :verify

:sign_signtool
if "%SIGNTOOL_PATH%"=="" set SIGNTOOL_PATH=signtool
if "%PHARMAUTO_CERT_PATH%"=="" (
  echo [sign] ERROR: PHARMAUTO_CERT_PATH 미설정
  exit /b 1
)
if "%PHARMAUTO_CERT_PW%"=="" (
  echo [sign] ERROR: PHARMAUTO_CERT_PW 미설정
  exit /b 1
)

echo [sign] signtool 서명 중 — %FILE%
"%SIGNTOOL_PATH%" sign /fd SHA256 /tr http://timestamp.sectigo.com /td SHA256 /f "%PHARMAUTO_CERT_PATH%" /p %PHARMAUTO_CERT_PW% "%FILE%"
if errorlevel 1 (
  echo [sign] ERROR: signtool 서명 실패
  exit /b 1
)

:verify
echo [sign] 서명 검증 중...
powershell -NoProfile -Command "$sig = Get-AuthenticodeSignature '%FILE%'; if ($sig.Status -ne 'Valid') { Write-Host '[sign] VERIFY FAILED:' $sig.Status '-' $sig.StatusMessage; exit 1 } else { Write-Host '[sign] VERIFY OK —' $sig.SignerCertificate.Subject }"
if errorlevel 1 (
  echo [sign] ERROR: 서명 검증 실패
  exit /b 1
)

endlocal
exit /b 0
