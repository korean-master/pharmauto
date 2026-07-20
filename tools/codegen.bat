@echo off
chcp 65001 >nul
cd /d %~dp0..
if "%1"=="" (
    echo Usage: codegen.bat [url]
    echo Example: codegen.bat https://www.esehwa.co.kr
    set /p URL=URL:
) else (
    set URL=%1
)
echo Opening playwright codegen: %URL%
venv312\Scripts\python.exe -m playwright codegen %URL%
pause
