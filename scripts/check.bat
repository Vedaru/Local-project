@echo off
REM Runtime Health Check - Batch Version

setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "AUTO_PAUSE=1"
if /I "%~1"=="--no-pause" set "AUTO_PAUSE=0"

pushd "%~dp0.."
set "PROJECT_DIR=%CD%\"
popd
set "RUNTIME_DIR=%PROJECT_DIR%runtime"
set "PYTHON_EXE=%RUNTIME_DIR%\python.exe"
set "PIP_EXE=%RUNTIME_DIR%\Scripts\pip.exe"
set "PTH_FILE=%RUNTIME_DIR%\python39._pth"

echo ============================================
echo Project Local - Runtime 健康检查
echo ============================================
echo.

set "TOTAL=0"
set "PASSED=0"
set "USING_RUNTIME=0"
set "ACTIVE_PYTHON="
set "PIP_MODE="

if exist "%PYTHON_EXE%" (
    set "USING_RUNTIME=1"
    set "ACTIVE_PYTHON=%PYTHON_EXE%"
    set "PIP_MODE=runtime"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        set "ACTIVE_PYTHON="
    ) else (
        set "ACTIVE_PYTHON=python"
        set "PIP_MODE=system"
    )
)

if "%USING_RUNTIME%"=="1" (
    call :check_exists "Runtime 目录存在" "%RUNTIME_DIR%" "请确保 runtime 目录存在"
    call :check_exists "python.exe 存在" "%PYTHON_EXE%" "缺少 Python 解释器"
    call :check_exists "pip.exe 存在" "%PIP_EXE%" "缺少 pip"
    call :check_exists "python39._pth 存在" "%PTH_FILE%" "缺少路径配置文件"

    if exist "%PTH_FILE%" (
        findstr /I /C:"import site" "%PTH_FILE%" >nul
        if errorlevel 1 (
            call :check_false "包含 import site" "需要启用 site-packages"
        ) else (
            call :check_true "包含 import site"
        )

        findstr /C:".." "%PTH_FILE%" >nul
        if errorlevel 1 (
            call :check_false "包含项目路径" "需要添加项目根目录到路径"
        ) else (
            call :check_true "包含项目路径"
        )
    )
) else (
    call :check_optional_exists "Runtime 目录存在" "%RUNTIME_DIR%" "当前使用 PATH Python，runtime 可选"
    call :check_optional_exists "python.exe 存在" "%PYTHON_EXE%" "当前使用 PATH Python，runtime 可选"
    call :check_optional_exists "pip.exe 存在" "%PIP_EXE%" "当前使用 PATH Python，runtime 可选"
    call :check_optional_exists "python39._pth 存在" "%PTH_FILE%" "当前使用 PATH Python，runtime 可选"
)

if not "%ACTIVE_PYTHON%"=="" (
    "%ACTIVE_PYTHON%" --version >nul 2>&1
    if errorlevel 1 (
        call :check_false "Python 可执行" "Python 解释器无法运行"
    ) else (
        for /f "delims=" %%V in ('"%ACTIVE_PYTHON%" --version 2^>^&1') do set "PYVER=%%V"
        call :check_true "Python 版本: !PYVER!"
    )

    "%ACTIVE_PYTHON%" -m pip --version >nul 2>&1
    if errorlevel 1 (
        call :check_false "Pip 可执行" "pip 无法运行"
    ) else (
        for /f "tokens=1,2 delims= " %%A in ('"%ACTIVE_PYTHON%" -m pip --version 2^>^&1') do set "PIPVER=%%A %%B"
        call :check_true "Pip 版本: !PIPVER!"

        "%ACTIVE_PYTHON%" -m pip list > "%TEMP%\runtime_pkg_list.txt" 2>nul
        call :check_pkg "OpenAI SDK" "openai"
        call :check_pkg "PyQt6" "PyQt6"
        call :check_pkg "Requests" "requests"
        del /q "%TEMP%\runtime_pkg_list.txt" >nul 2>&1
    )

    pushd "%PROJECT_DIR%" >nul
    "%ACTIVE_PYTHON%" -c "import modules;print('OK')" > "%TEMP%\runtime_import_test.txt" 2>&1
    findstr /I /C:"OK" "%TEMP%\runtime_import_test.txt" >nul
    if errorlevel 1 (
        call :check_false "导入 modules 包" "检查 Python 环境与项目路径"
    ) else (
        call :check_true "导入 modules 包"
    )
    del /q "%TEMP%\runtime_import_test.txt" >nul 2>&1
    popd >nul
) else (
    call :check_false "Python 可执行" "未找到可用 Python（runtime 与 PATH 均不可用）"
)

call :check_exists "main.py 存在" "%PROJECT_DIR%main.py" "缺少主入口"
call :check_exists "project_config.yaml 存在" "%PROJECT_DIR%project_config.yaml" "缺少统一配置文件"
call :check_exists "requirements.txt 存在" "%PROJECT_DIR%requirements.txt" "缺少依赖列表"
call :check_exists "modules 包存在" "%PROJECT_DIR%modules\__init__.py" "缺少 modules 包"
call :check_exists "scripts\start.bat 存在" "%PROJECT_DIR%scripts\start.bat" "缺少启动脚本"
call :check_exists "scripts\install.bat 存在" "%PROJECT_DIR%scripts\install.bat" "缺少安装脚本"

echo.
echo ============================================
echo 检查完成
echo ============================================
set /a RATE=0
if not "%TOTAL%"=="0" set /a RATE=PASSED*100/TOTAL
echo 通过: %PASSED% / %TOTAL% (%RATE%%)

if "%PASSED%"=="%TOTAL%" (
    echo.
    echo [OK] Runtime 环境配置正确，可以启动项目！
    echo 运行: .\scripts\start.bat
) else if %RATE% GEQ 70 (
    echo.
    echo [WARN] Runtime 环境部分配置有问题，建议修复后使用
    echo 如果缺少依赖，运行: .\scripts\install.bat
) else (
    echo.
    echo [ERROR] Runtime 环境配置有严重问题，请按提示修复
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
    echo [✓] %~1
) else (
    echo [✗] %~1
    if not "%~3"=="" echo     提示: %~3
)
exit /b 0

:check_optional_exists
if exist "%~2" (
    echo [✓] %~1
) else (
    echo [-] %~1
    if not "%~3"=="" echo     提示: %~3
)
exit /b 0

:check_pkg
set /a TOTAL+=1
findstr /I /C:"%~2" "%TEMP%\runtime_pkg_list.txt" >nul
if errorlevel 1 (
    echo [✗] %~1
    echo     提示: 运行 scripts\install.bat 安装依赖
) else (
    set /a PASSED+=1
    echo [✓] %~1
)
exit /b 0

:check_true
set /a TOTAL+=1
set /a PASSED+=1
echo [✓] %~1
exit /b 0

:check_false
set /a TOTAL+=1
echo [✗] %~1
if not "%~2"=="" echo     提示: %~2
exit /b 0
