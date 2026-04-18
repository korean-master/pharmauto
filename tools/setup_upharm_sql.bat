@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo =====================================
echo  PharmAuto 유팜 SQL 읽기전용 계정 설정
echo =====================================
echo.

:: 관리자 권한 체크
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] 관리자 권한 필요
    exit /b 1
)

:: 이미 설정되어 있으면 스킵
sqlcmd -S . -U pharmauto_ro -P PharmAuto2026Ro! -Q "SELECT 1" >nul 2>&1
if %errorlevel% equ 0 (
    echo [완료] pharmauto_ro 이미 존재하고 정상 작동
    exit /b 0
)

echo [1/6] SQL Server 중지...
net stop MSSQLSERVER >nul 2>&1
timeout /t 2 /nobreak >nul

echo [2/6] 단일 사용자 모드로 시작...
net start MSSQLSERVER /m"SQLCMD" >nul 2>&1
timeout /t 4 /nobreak >nul

:: sqlcmd 접속 방식 결정 (현재 관리자 or SYSTEM)
set SQLCMD_BASE=sqlcmd -S . -E
sqlcmd -S . -E -Q "SELECT 1" >nul 2>&1
if %errorlevel% neq 0 (
    echo      현재 계정 접속 실패 -^> SYSTEM 경유
    set SQLCMD_BASE="%~dp0psexec64.exe" -accepteula -nobanner -s sqlcmd -S . -E
)

echo [3/6] pharmauto_ro 로그인 생성...
%SQLCMD_BASE% -Q "IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name=N'pharmauto_ro') CREATE LOGIN pharmauto_ro WITH PASSWORD='PharmAuto2026Ro!', CHECK_POLICY=OFF"
if %errorlevel% neq 0 (
    echo [오류] 로그인 생성 실패
    net stop MSSQLSERVER >nul 2>&1
    net start MSSQLSERVER >nul 2>&1
    exit /b 2
)

echo [4/6] 모든 사용자 DB 에 읽기 권한 부여...
%SQLCMD_BASE% -Q "DECLARE @sql NVARCHAR(MAX)=N''; SELECT @sql = @sql + 'USE [' + name + ']; IF NOT EXISTS(SELECT 1 FROM sys.database_principals WHERE name=''pharmauto_ro'') BEGIN CREATE USER pharmauto_ro FOR LOGIN pharmauto_ro; ALTER ROLE db_datareader ADD MEMBER pharmauto_ro; END; ' FROM sys.databases WHERE database_id > 4 AND state_desc='ONLINE' AND is_read_only=0; EXEC sp_executesql @sql;"

echo [5/6] Mixed Mode 확인/활성화...
%SQLCMD_BASE% -Q "EXEC xp_instance_regwrite N'HKEY_LOCAL_MACHINE', N'Software\Microsoft\MSSQLServer\MSSQLServer', N'LoginMode', REG_DWORD, 2" >nul 2>&1

echo [6/6] SQL Server 정상 모드로 재시작...
net stop MSSQLSERVER >nul 2>&1
net start MSSQLSERVER >nul 2>&1
timeout /t 4 /nobreak >nul

:: 최종 검증
sqlcmd -S . -U pharmauto_ro -P PharmAuto2026Ro! -Q "SELECT 1" >nul 2>&1
if %errorlevel% equ 0 (
    echo.
    echo ===== 설정 완료 =====
    exit /b 0
) else (
    echo.
    echo [오류] 최종 검증 실패 - 수동 확인 필요
    exit /b 3
)
