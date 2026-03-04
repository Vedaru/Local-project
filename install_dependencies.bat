@echo off
REM Project Local - Install Dependencies with Runtime
REM 使用独立的 Python Runtime 安装项目依赖

setlocal

set "RUNTIME_DIR=%~dp0runtime"
set "PYTHON_EXE=%RUNTIME_DIR%\python.exe"
set "PIP_EXE=%RUNTIME_DIR%\Scripts\pip.exe"
set "PROJECT_DIR=%~dp0"

REM 检查 runtime Python 是否存在
if not exist "%PYTHON_EXE%" (
    echo [错误] 找不到 Python Runtime: %PYTHON_EXE%
    echo 请确保 runtime 目录下包含完整的 Python 3.9 运行时
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"

echo ============================================
echo Project Local - 依赖安装
echo ============================================
echo Python: %PYTHON_EXE%
echo Pip: %PIP_EXE%
echo ============================================
echo.

REM 升级 pip
echo [1/3] 升级 pip...
"%PYTHON_EXE%" -m pip install --upgrade pip

if errorlevel 1 (
    echo [错误] 升级 pip 失败
    pause
    exit /b 1
)

echo.
echo [2/3] 安装生产环境依赖...
"%PIP_EXE%" install -r requirements.txt

if errorlevel 1 (
    echo [错误] 安装依赖失败
    pause
    exit /b 1
)

echo.
echo [3/3] 安装额外的 GPT-SoVITS 依赖...
cd modules\gpt_sovits
if exist requirements.txt (
    "%PIP_EXE%" install -r requirements.txt
)
cd ..\..

echo.
echo ============================================
echo 依赖安装完成！
echo ============================================
echo.
echo 现在可以运行以下命令启动项目：
echo   run_with_runtime.bat
echo   或
echo   run_with_runtime.ps1
echo ============================================

pause
endlocal
