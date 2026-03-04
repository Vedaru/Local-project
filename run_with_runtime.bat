@echo off
REM Project Local - Runtime Launcher
REM 使用独立的 Python Runtime 启动项目

setlocal

set "RUNTIME_DIR=%~dp0runtime"
set "PYTHON_EXE=%RUNTIME_DIR%\python.exe"
set "PROJECT_DIR=%~dp0"

REM 检查 runtime Python 是否存在
if not exist "%PYTHON_EXE%" (
    echo [错误] 找不到 Python Runtime: %PYTHON_EXE%
    echo 请确保 runtime 目录下包含完整的 Python 3.9 运行时
    pause
    exit /b 1
)

REM 设置环境变量
set "CT2_USE_CUDA=0"
if not defined LOKY_MAX_CPU_COUNT (
    for /f %%i in ('wmic cpu get NumberOfLogicalProcessors /value ^| findstr "="') do set %%i
    set "LOKY_MAX_CPU_COUNT=%NumberOfLogicalProcessors%"
)

REM 切换到项目目录
cd /d "%PROJECT_DIR%"

echo ============================================
echo Project Local - 使用独立 Runtime 启动
echo ============================================
echo Python: %PYTHON_EXE%
echo 项目目录: %PROJECT_DIR%
echo ============================================
echo.

REM 启动主程序
"%PYTHON_EXE%" main.py %*

if errorlevel 1 (
    echo.
    echo [错误] 程序执行失败，错误代码: %errorlevel%
    pause
)

endlocal
