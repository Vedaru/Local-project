@echo off
REM Runtime health check (ASCII-only batch)

setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "AUTO_PAUSE=1"
if /I "%~1"=="--no-pause" set "AUTO_PAUSE=0"

pushd "%~dp0.."
set "PROJECT_DIR=%CD%\"
popd
set "RUNTIME_DIR=%PROJECT_DIR%runtime"
set "PYTHON_EXE=%RUNTIME_DIR%\python.exe"
set "PTH_FILE="
set "VERSION_FILE=%PROJECT_DIR%scripts\runtime_version.txt"

echo ============================================
echo Project Local - runtime health check
echo ============================================
echo.

set "TOTAL=0"
set "PASSED=0"
set "ACTIVE_PYTHON="

if not exist "%PYTHON_EXE%" (
    call :check_false "python.exe exists" "Run scripts\setup_runtime.bat"
    goto :check_project_files
)

set "ACTIVE_PYTHON=%PYTHON_EXE%"
call :check_exists "Runtime directory" "%RUNTIME_DIR%" "Run scripts\setup_runtime.bat"
call :check_exists "python.exe" "%PYTHON_EXE%" "Run scripts\setup_runtime.bat"
call :check_exists "runtime_version.txt" "%VERSION_FILE%" "Missing version pin file"

for %%F in ("%RUNTIME_DIR%\python*._pth") do set "PTH_FILE=%%~f"
if defined PTH_FILE (
    call :check_true "path config file exists"
    findstr /I /C:"import site" "%PTH_FILE%" >nul
    if errorlevel 1 (
        call :check_false "import site in _pth" "Re-run scripts\setup_runtime.bat"
    ) else (
        call :check_true "import site enabled"
    )
    findstr /C:".." "%PTH_FILE%" >nul
    if errorlevel 1 (
        call :check_false "project root in _pth" "Add .. line to _pth"
    ) else (
        call :check_true "project root in _pth"
    )
) else (
    call :check_false "python*._pth exists" "Run scripts\setup_runtime.bat"
)

if exist "%VERSION_FILE%" (
    set /p PINNED_VER=<"%VERSION_FILE%"
    for /f "delims=" %%V in ('"%PYTHON_EXE%" --version 2^>^&1') do set "PYVER=%%V"
    echo !PYVER! | findstr /C:"!PINNED_VER!" >nul
    if errorlevel 1 (
        call :check_false "version matches runtime_version.txt" "want !PINNED_VER! got !PYVER!"
    ) else (
        call :check_true "version matches runtime_version.txt"
    )
)

if not "%ACTIVE_PYTHON%"=="" (
    "%ACTIVE_PYTHON%" --version >nul 2>&1
    if errorlevel 1 (
        call :check_false "Python runs"
    ) else (
        for /f "delims=" %%V in ('"%ACTIVE_PYTHON%" --version 2^>^&1') do set "PYVER=%%V"
        call :check_true "Python version: !PYVER!"
    )

    "%ACTIVE_PYTHON%" -m pip --version >nul 2>&1
    if errorlevel 1 (
        call :check_false "pip runs"
    ) else (
        for /f "tokens=1,2 delims= " %%A in ('"%ACTIVE_PYTHON%" -m pip --version 2^>^&1') do set "PIPVER=%%A %%B"
        call :check_true "pip version: !PIPVER!"

        "%ACTIVE_PYTHON%" -m pip list > "%TEMP%\runtime_pkg_list.txt" 2>nul
        call :check_pkg "OpenAI SDK" "openai"
        call :check_pkg "PyQt6" "PyQt6"
        call :check_pkg "Requests" "requests"
        call :check_pkg "FastAPI" "fastapi"
        del /q "%TEMP%\runtime_pkg_list.txt" >nul 2>&1
    )

    pushd "%PROJECT_DIR%" >nul
    "%ACTIVE_PYTHON%" -c "import modules;print('OK')" > "%TEMP%\runtime_import_test.txt" 2>&1
    findstr /I /C:"OK" "%TEMP%\runtime_import_test.txt" >nul
    if errorlevel 1 (
        call :check_false "import modules"
    ) else (
        call :check_true "import modules"
    )
    del /q "%TEMP%\runtime_import_test.txt" >nul 2>&1
    popd >nul
) else (
    call :check_false "Python available" "runtime\\python.exe missing"
)

:check_project_files
call :check_exists "main.py" "%PROJECT_DIR%main.py"
call :check_exists "project_config.yaml" "%PROJECT_DIR%project_config.yaml"
call :check_exists "requirements.txt" "%PROJECT_DIR%requirements.txt"
call :check_exists "modules package" "%PROJECT_DIR%modules\__init__.py"
call :check_exists "scripts\start.bat" "%PROJECT_DIR%scripts\start.bat"
call :check_exists "scripts\install.bat" "%PROJECT_DIR%scripts\install.bat"

echo.
echo ============================================
echo Done
echo ============================================
set /a RATE=0
if not "%TOTAL%"=="0" set /a RATE=PASSED*100/TOTAL
echo Pass: %PASSED% / %TOTAL% (%RATE%%)

if "%PASSED%"=="%TOTAL%" (
    echo.
    echo [OK] Ready. Run scripts\start.bat or run_with_runtime.bat
) else if %RATE% GEQ 70 (
    echo.
    echo [WARN] Some checks failed. Try scripts\install.bat
) else (
    echo.
    echo [ERROR] Fix issues above, then scripts\install.bat
)

if "%AUTO_PAUSE%"=="1" (
    echo.
    pause
)

endlocal
exit /b 0

:check_exists
set /a TOTAL+=1
if exist "%~2" (
    set /a PASSED+=1
    echo [OK] %~1
) else (
    echo [FAIL] %~1
    if not "%~3"=="" echo       %~3
)
exit /b 0

:check_pkg
set /a TOTAL+=1
findstr /I /C:"%~2" "%TEMP%\runtime_pkg_list.txt" >nul
if errorlevel 1 (
    echo [FAIL] %~1
    echo       Run scripts\install.bat
) else (
    set /a PASSED+=1
    echo [OK] %~1
)
exit /b 0

:check_true
set /a TOTAL+=1
set /a PASSED+=1
echo [OK] %~1
exit /b 0

:check_false
set /a TOTAL+=1
echo [FAIL] %~1
if not "%~2"=="" echo       %~2
exit /b 0
