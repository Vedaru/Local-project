@echo off
REM Project Local - Install Dependencies with Runtime

setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "PROJECT_DIR=%~dp0"
set "RUNTIME_DIR=%PROJECT_DIR%runtime"
set "PYTHON_EXE=%RUNTIME_DIR%\python.exe"

set "INSTALL_DEV=0"
set "USE_MIRROR=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="-Dev" (
    set "INSTALL_DEV=1"
    shift
    goto parse_args
)
if /I "%~1"=="-Mirror" (
    set "USE_MIRROR=1"
    shift
    goto parse_args
)
echo [WARN] 未识别参数: %~1
shift
goto parse_args

:args_done
if not exist "%PYTHON_EXE%" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [错误] 找不到 Python Runtime: %PYTHON_EXE%
        echo 且 PATH 中未发现可用 python，请先安装 Python 或恢复 runtime 目录
        pause
        exit /b 1
    )
    set "PYTHON_EXE=python"
    echo [WARN] 未找到 runtime\python.exe，已回退使用 PATH 中的 Python。
)

cd /d "%PROJECT_DIR%"

set "PIP_INDEX_ARGS="
if "%USE_MIRROR%"=="1" (
    set "PIP_INDEX_ARGS=-i https://pypi.tuna.tsinghua.edu.cn/simple"
    echo [信息] 使用清华大学镜像源
)

echo ============================================
echo Project Local - 依赖安装
echo ============================================
echo Python: %PYTHON_EXE%
echo Pip: %PYTHON_EXE% -m pip
echo ============================================
echo.

echo [1/4] 升级 pip...
"%PYTHON_EXE%" -m pip install --upgrade pip %PIP_INDEX_ARGS%
if errorlevel 1 (
    echo [错误] 升级 pip 失败
    pause
    exit /b 1
)

echo.
echo [2/4] 安装生产环境依赖...
"%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%requirements.txt" %PIP_INDEX_ARGS%
if errorlevel 1 (
    echo [错误] 安装生产环境依赖失败
    pause
    exit /b 1
)

echo.
echo [3/4] 检查 GPT-SoVITS 依赖...
if exist "%PROJECT_DIR%modules\gpt_sovits\requirements.txt" (
    "%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%modules\gpt_sovits\requirements.txt" %PIP_INDEX_ARGS%
    if errorlevel 1 (
        echo [WARN] GPT-SoVITS 依赖安装失败（非致命错误）
    )
) else (
    echo [INFO] 未找到 modules\gpt_sovits\requirements.txt，跳过
)

echo.
if "%INSTALL_DEV%"=="1" (
    echo [4/4] 安装开发环境依赖...
    for %%P in (
        "pytest>=7.4.0"
        "pytest-cov>=4.1.0"
        "pytest-asyncio>=0.21.0"
        "pytest-mock>=3.12.0"
        "black>=23.0.0"
        "isort>=5.12.0"
        "ruff>=0.1.0"
        "mypy>=1.5.0"
        "pre-commit"
    ) do (
        "%PYTHON_EXE%" -m pip install %%~P %PIP_INDEX_ARGS%
        if errorlevel 1 echo [WARN] 安装 %%~P 失败（已继续）
    )
) else (
    echo [4/4] 跳过开发环境依赖（使用 -Dev 参数安装）
)

echo.
echo [5/5] 检查并构建 C++ 加速引擎...
set "VOICE_CPP_SOURCE=%PROJECT_DIR%cpp_modules\voice_cpp_engine"
if exist "%VOICE_CPP_SOURCE%\CMakeLists.txt" (
    echo [INFO] 发现 voice_cpp_engine，开始 CMake 构建...
    set "VOICE_CPP_BUILD=%PROJECT_DIR%build\voice_cpp_engine"
    cmake -S "%VOICE_CPP_SOURCE%" -B "%VOICE_CPP_BUILD%" -DCMAKE_BUILD_TYPE=Release
    if errorlevel 1 (
        echo [WARN] voice_cpp_engine CMake 配置失败，跳过构建（非致命错误）
        goto :skip_voice_cpp
    )
    cmake --build "%VOICE_CPP_BUILD%" --config Release
    if errorlevel 1 (
        echo [WARN] voice_cpp_engine 构建失败（非致命错误）
        goto :skip_voice_cpp
    )
    if exist "%VOICE_CPP_BUILD%\Release\voice_cpp_engine.dll" (
        echo [OK] voice_cpp_engine.dll 构建成功
    ) else if exist "%VOICE_CPP_BUILD%\voice_cpp_engine.dll" (
        echo [OK] voice_cpp_engine.dll 构建成功
    ) else (
        echo [WARN] voice_cpp_engine 构建完成但未找到输出 DLL
    )
) else (
    echo [INFO] 未找到 voice_cpp_engine 源码，跳过 C++ 引擎构建
)
:skip_voice_cpp

echo.
echo ============================================
echo 依赖安装完成！
echo ============================================
echo 现在可以运行:
echo   .\run_with_runtime.bat
echo ============================================

endlocal
exit /b 0
