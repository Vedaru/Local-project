@echo off
REM Install project runtime (official embeddable Python; see runtime_version.txt)
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

pushd "%~dp0.."
set "PROJECT_DIR=%CD%\"
popd

set "RUNTIME_DIR=%PROJECT_DIR%runtime"
set "PYTHON_EXE=%RUNTIME_DIR%\python.exe"
set "VERSION_FILE=%PROJECT_DIR%scripts\runtime_version.txt"

if not exist "%VERSION_FILE%" (
    echo [ERROR] Missing %VERSION_FILE%
    pause
    exit /b 1
)

set /p RUNTIME_VERSION=<"%VERSION_FILE%"
set "RUNTIME_VERSION=%RUNTIME_VERSION: =%"

echo ============================================
echo Project Local - Runtime Python %RUNTIME_VERSION%
echo ============================================
echo Target: %RUNTIME_DIR%
echo Source: python.org embed only (no Conda / PATH Python)
echo ============================================
echo.

if /I "%~1"=="--force" (
    if exist "%RUNTIME_DIR%" (
        echo [INFO] Removing existing runtime...
        rmdir /s /q "%RUNTIME_DIR%"
    )
)

if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" --version 2>nul | findstr /C:"%RUNTIME_VERSION%" >nul
    if not errorlevel 1 (
        echo [OK] Runtime already installed: %PYTHON_EXE%
        goto :verify_pth
    )
    echo [WARN] Version mismatch, reinstalling...
    rmdir /s /q "%RUNTIME_DIR%" 2>nul
)

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"

set "ZIP_NAME=python-%RUNTIME_VERSION%-embed-amd64.zip"
set "ZIP_URL=https://www.python.org/ftp/python/%RUNTIME_VERSION%/%ZIP_NAME%"
set "ZIP_PATH=%RUNTIME_DIR%\%ZIP_NAME%"

echo [1/4] Download %ZIP_NAME% ...
curl -fsSL -o "%ZIP_PATH%" "%ZIP_URL%"
if errorlevel 1 (
    echo [ERROR] Download failed: %ZIP_URL%
    pause
    exit /b 1
)

echo [2/4] Extract to runtime ...
tar -xf "%ZIP_PATH%" -C "%RUNTIME_DIR%"
del /q "%ZIP_PATH%" >nul 2>&1

if not exist "%PYTHON_EXE%" (
    echo [ERROR] python.exe not found after extract: %PYTHON_EXE%
    pause
    exit /b 1
)

call :write_pth "%RUNTIME_VERSION%"

echo [3/4] Install pip ...
set "GET_PIP=%RUNTIME_DIR%\_get-pip.py"
curl -fsSL -o "%GET_PIP%" "https://bootstrap.pypa.io/get-pip.py"
if errorlevel 1 (
    echo [ERROR] Failed to download get-pip.py
    pause
    exit /b 1
)
"%PYTHON_EXE%" "%GET_PIP%"
set "_PIP_EC=!ERRORLEVEL!"
del /q "%GET_PIP%" >nul 2>&1
if not "!_PIP_EC!"=="0" (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)

echo [4/4] Verify ...
"%PYTHON_EXE%" --version
if errorlevel 1 (
    echo [ERROR] runtime python failed
    pause
    exit /b 1
)

:verify_pth
call :write_pth "%RUNTIME_VERSION%"

echo.
echo [OK] Runtime ready: %PYTHON_EXE%
echo Next: scripts\install.bat
echo ============================================
endlocal
exit /b 0

:write_pth
set "VER=%~1"
for /f "tokens=1,2 delims=." %%a in ("%VER%") do (
    set "PTH_NAME=python%%a%%b._pth"
    set "ZIP_LINE=python%%a%%b.zip"
)
set "PTH_FILE=%RUNTIME_DIR%\!PTH_NAME!"
if not exist "!PTH_FILE!" (
    echo [ERROR] Missing path file: !PTH_FILE!
    exit /b 1
)
> "!PTH_FILE!" (
    echo !ZIP_LINE!
    echo .
    echo ..
    echo import site
)
echo [INFO] Wrote !PTH_NAME!
exit /b 0
