@echo off
REM Install dependencies into runtime\ (ASCII-only batch)
REM Usage: install.bat [-Mirror] [-SkipTorch] [-Dev] [-Optional] [-All]
REM PyTorch + GPT-SoVITS stack in requirements.txt are installed by default.

setlocal EnableExtensions EnableDelayedExpansion

pushd "%~dp0.."
set "PROJECT_DIR=%CD%\"
popd
set "RUNTIME_DIR=%PROJECT_DIR%runtime"
set "PYTHON_EXE=%RUNTIME_DIR%\python.exe"

set "INSTALL_DEV=0"
set "USE_MIRROR=0"
set "INSTALL_TORCH=1"
set "INSTALL_OPTIONAL=0"
set "SKIP_TORCH=0"

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
if /I "%~1"=="-SkipTorch" (
    set "SKIP_TORCH=1"
    set "INSTALL_TORCH=0"
    shift
    goto parse_args
)
if /I "%~1"=="-Torch" (
    set "INSTALL_TORCH=1"
    shift
    goto parse_args
)
if /I "%~1"=="-Optional" (
    set "INSTALL_OPTIONAL=1"
    shift
    goto parse_args
)
if /I "%~1"=="-All" (
    set "INSTALL_DEV=1"
    set "INSTALL_OPTIONAL=1"
    set "INSTALL_TORCH=1"
    shift
    goto parse_args
)
if /I "%~1"=="-GptSovits" (
    echo [WARN] -GptSovits is deprecated: GPT-SoVITS deps are always in requirements.txt
    shift
    goto parse_args
)
echo [WARN] Unknown argument: %~1
echo Options: -Mirror -SkipTorch -Dev -Optional -All
shift
goto parse_args

:args_done
if not exist "%PYTHON_EXE%" (
    echo [INFO] runtime\python.exe not found, installing embeddable Python...
    call "%PROJECT_DIR%scripts\setup_runtime.bat"
    if errorlevel 1 (
        echo [ERROR] setup_runtime.bat failed. Check network and retry.
        pause
        exit /b 1
    )
)
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Still missing: %PYTHON_EXE%
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"
set "PYTHONNOUSERSITE=1"

set "PIP_RETRY=--retries 5 --timeout 120"
set "PIP_INDEX_ARGS="
if "%USE_MIRROR%"=="1" (
    set "PIP_INDEX_ARGS=-i https://pypi.tuna.tsinghua.edu.cn/simple"
    echo [INFO] Using Tsinghua PyPI mirror
) else (
    echo [TIP] If download fails, retry: scripts\install.bat -Mirror
)

echo ============================================
echo Project Local - dependency install
echo ============================================
echo Python: %PYTHON_EXE%
echo.
echo Default: PyTorch + GPT-SoVITS (requirements.txt)
echo Options:
echo   -Mirror     Tsinghua mirror
echo   -SkipTorch  skip PyTorch (not recommended)
echo   -Dev        dev/test tools from requirements.txt
echo   -Optional   aws, crawl4ai
echo   -All        -Dev + -Optional
echo ============================================
echo.

echo [1/6] Upgrade pip, setuptools, wheel, Cython...
"%PYTHON_EXE%" -m pip install %PIP_RETRY% --upgrade pip "setuptools>=75.8.0,<82" wheel Cython %PIP_INDEX_ARGS%
if errorlevel 1 (
    echo [ERROR] pip/setuptools upgrade failed
    pause
    exit /b 1
)

echo.
if "%INSTALL_TORCH%"=="1" (
    echo [2/6] PyTorch ^(required, ^>=2.6.0 for transformers / GPT-SoVITS^)...
    echo [INFO] Trying CUDA 12.4 wheels ^(cu124^)...
    call :install_pytorch cu124
    if errorlevel 1 (
        echo [WARN] cu124 failed, trying CPU wheels...
        call :install_pytorch cpu
        if errorlevel 1 (
            echo [ERROR] PyTorch 2.6+ install failed on cu124 and cpu.
            echo        See https://pytorch.org/get-started/locally/
            pause
            exit /b 1
        )
        echo [OK] PyTorch CPU installed
    ) else (
        echo [OK] PyTorch CUDA 12.4 ^(cu124^) installed
    )
) else (
    echo [2/6] Skip PyTorch ^(-SkipTorch^)
)

echo.
echo [3/6] requirements.txt ^(core + GPT-SoVITS + microservices^)...
"%PYTHON_EXE%" -m pip install %PIP_RETRY% -r "%PROJECT_DIR%requirements.txt" %PIP_INDEX_ARGS%
if errorlevel 1 (
    echo [ERROR] requirements install failed
    pause
    exit /b 1
)

echo.
echo [4/6] Ensure httpx HTTP/2...
"%PYTHON_EXE%" -m pip install %PIP_RETRY% "httpx[http2]" h2 %PIP_INDEX_ARGS%

echo.
echo [5/6] Microservice preflight...
"%PYTHON_EXE%" "%PROJECT_DIR%scripts\ensure_microservice_deps.py"
if errorlevel 1 (
    echo [WARN] Preflight reported issues; see log above
)

echo.
if "%INSTALL_OPTIONAL%"=="1" (
    echo [6/6] Optional packages...
    "%PYTHON_EXE%" -m pip install %PIP_RETRY% boto3 crawl4ai %PIP_INDEX_ARGS%
    echo [OK] Optional deps done
) else (
    echo [6/6] Skip optional ^(use install.bat -Optional^)
)

if "%INSTALL_DEV%"=="1" (
    echo [INFO] Dev tools are listed in requirements.txt and installed with step 3
)

echo.
echo [INFO] Optional language packs ^(manual^):
echo   Japanese TTS: pip install pyopenjtalk
echo   Korean TTS:   pip install jamo ko_pron g2pk2

echo.
echo [INFO] C++ voice engine ^(optional^)...
set "VOICE_CPP_SOURCE=%PROJECT_DIR%cpp_modules\voice_cpp_engine"
if exist "%VOICE_CPP_SOURCE%\CMakeLists.txt" (
    set "VOICE_CPP_BUILD=%PROJECT_DIR%build\voice_cpp_engine"
    cmake -S "%VOICE_CPP_SOURCE%" -B "%VOICE_CPP_BUILD%" -DCMAKE_BUILD_TYPE=Release
    if errorlevel 1 (
        echo [WARN] voice_cpp_engine CMake configure failed ^(skipped^)
        goto :skip_voice_cpp
    )
    cmake --build "%VOICE_CPP_BUILD%" --config Release
    if errorlevel 1 (
        echo [WARN] voice_cpp_engine build failed ^(skipped^)
        goto :skip_voice_cpp
    )
    if exist "%VOICE_CPP_BUILD%\Release\voice_cpp_engine.dll" (
        echo [OK] voice_cpp_engine.dll built
    ) else if exist "%VOICE_CPP_BUILD%\voice_cpp_engine.dll" (
        echo [OK] voice_cpp_engine.dll built
    ) else (
        echo [WARN] Build finished but DLL not found
    )
) else (
    echo [INFO] No voice_cpp_engine sources, skipped
)
:skip_voice_cpp

echo.
echo ============================================
echo Install finished.
echo ============================================
echo   [x] setuptools + requirements.txt
if "%INSTALL_TORCH%"=="1" echo   [x] PyTorch ^(GPT-SoVITS^)
if "%INSTALL_OPTIONAL%"=="1" echo   [x] Optional extras
echo.
echo Run: scripts\start.bat  or  run_with_runtime.bat
echo ============================================

endlocal
exit /b 0

:install_pytorch
REM Subroutine: arg1 = cu124 or cpu (avoids empty %%VAR%% in parenthesized blocks)
"%PYTHON_EXE%" -m pip install --retries 5 --timeout 120 "torch>=2.6.0" "torchaudio>=2.6.0" "torchvision>=0.21.0" --index-url https://download.pytorch.org/whl/%~1
exit /b %ERRORLEVEL%
