@echo off
chcp 65001 >nul
echo ============================================
echo   PharmAuto 빌드 스크립트
echo ============================================
echo.

:: 1. 의존성 설치
echo [1/6] 의존성 설치 중...
pip install -r requirements.txt >nul 2>&1
pip install pyinstaller >nul 2>&1

:: 2. Playwright 브라우저 설치
echo [2/6] Playwright Chromium 확인 중...
playwright install chromium >nul 2>&1

:: 3. 아이콘 확인
if not exist ui\icons\pharmauto.ico (
    echo [3/6] 경고: 아이콘 파일 없음 (ui\icons\pharmauto.ico)
    pause
    exit /b 1
) else (
    echo [3/6] 아이콘 파일 확인 완료
)

:: 4. PyInstaller 빌드
echo [4/6] PyInstaller 빌드 중... (시간이 좀 걸립니다)
pyinstaller pharmauto.spec --clean --noconfirm

if %errorlevel% neq 0 (
    echo.
    echo   빌드 실패!
    pause
    exit /b 1
)

:: 5. 배포용 초기 설정 파일 생성 (사용자 데이터 유출 방지)
echo [5/6] 배포용 초기 파일 생성 중...
mkdir dist\PharmAuto\_internal\config 2>nul
mkdir dist\PharmAuto\_internal\config\selectors 2>nul
mkdir dist\PharmAuto\_internal\data 2>nul
echo {} > dist\PharmAuto\_internal\config\settings.json
echo {} > dist\PharmAuto\_internal\config\wholesalers.json
echo {} > dist\PharmAuto\_internal\config\exclusions.json

:: 6. Inno Setup 설치 프로그램 생성
echo [6/6] 설치 프로그램 생성 중...

set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if exist %ISCC% (
    %ISCC% installer.iss
    if %errorlevel% equ 0 (
        echo.
        echo ============================================
        echo   빌드 완료!
        echo   설치 파일: installer_output\PharmAutoSetup.exe
        echo ============================================
        echo.
        echo   이 파일 하나만 전달하면 됩니다.
    ) else (
        echo   Inno Setup 빌드 실패
    )
) else (
    echo   Inno Setup 미설치 - 설치 프로그램 생성 건너뜀
    echo   dist\PharmAuto 폴더를 압축해서 배포하세요.
    echo.
    echo   Inno Setup 설치: https://jrsoftware.org/isdl.php
)

echo.
pause
