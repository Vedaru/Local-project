@echo off
REM Project Local - Install Dependencies with Runtime
REM Usage: install_dependencies.bat [-Dev] [-Mirror] [-Torch] [-GptSovits] [-All]

setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

pushd "%~dp0.."
set "PROJECT_DIR=%CD%\"
popd
set "RUNTIME_DIR=%PROJECT_DIR%runtime"
set "PYTHON_EXE=%RUNTIME_DIR%\python.exe"

set "INSTALL_DEV=0"
set "USE_MIRROR=0"
set "INSTALL_TORCH=0"
set "INSTALL_GPT_SOVITS=0"
set "INSTALL_OPTIONAL=0"

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
if /I "%~1"=="-Torch" (
    set "INSTALL_TORCH=1"
    shift
    goto parse_args
)
if /I "%~1"=="-GptSovits" (
    set "INSTALL_GPT_SOVITS=1"
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
    set "INSTALL_TORCH=1"
    set "INSTALL_GPT_SOVITS=1"
    set "INSTALL_OPTIONAL=1"
    shift
    goto parse_args
)
echo [WARN] 未识别参数: %~1
echo 可用参数: -Dev -Mirror -Torch -GptSovits -Optional -All
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
echo.
echo 安装选项:
echo   -Dev        安装开发/测试依赖
echo   -Mirror     使用清华镜像源
echo   -Torch      安装 PyTorch (CUDA 12.1)
echo   -GptSovits  安装 GPT-SoVITS 语音合成依赖
echo   -Optional   安装可选依赖 (Docker, AWS, 爬虫等)
echo   -All        安装所有依赖
echo ============================================
echo.

REM ============================================================
REM Step 1: 升级 pip
REM ============================================================
echo [1/7] 升级 pip...
"%PYTHON_EXE%" -m pip install --upgrade pip %PIP_INDEX_ARGS%
if errorlevel 1 (
    echo [错误] 升级 pip 失败
    pause
    exit /b 1
)

REM ============================================================
REM Step 2: 安装核心依赖
REM ============================================================
echo.
echo [2/7] 安装核心依赖...
"%PYTHON_EXE%" -m pip install -r "%PROJECT_DIR%requirements.txt" %PIP_INDEX_ARGS%
if errorlevel 1 (
    echo [错误] 安装核心依赖失败
    pause
    exit /b 1
)

REM 额外确保 h2 已安装（httpx HTTP/2 支持）
"%PYTHON_EXE%" -m pip install "httpx[http2]" h2 %PIP_INDEX_ARGS%

REM ============================================================
REM Step 3: PyTorch 安装 (可选)
REM 注意: transformers>=4.38 要求 torch>=2.6.0 (CVE-2025-32434)
REM ============================================================
echo.
if "%INSTALL_TORCH%"=="1" (
    echo [3/7] 安装 PyTorch (CUDA 12.1, 要求 gt;=2.6.0)...
    "%PYTHON_EXE%" -m pip install "torch>=2.6.0" "torchaudio>=2.6.0" "torchvision>=0.21.0" --index-url https://download.pytorch.org/whl/cu121 %PIP_INDEX_ARGS%
    if errorlevel 1 (
        echo [WARN] PyTorch CUDA 12.1 安装失败，尝试安装 CPU 版本...
        "%PYTHON_EXE%" -m pip install "torch>=2.6.0" "torchaudio>=2.6.0" "torchvision>=0.21.0" --index-url https://download.pytorch.org/whl/cpu %PIP_INDEX_ARGS%
        if errorlevel 1 (
            echo [WARN] PyTorch 安装失败（非致命错误，请手动安装）
        ) else (
            echo [OK] PyTorch CPU 版本安装成功
        )
    ) else (
        echo [OK] PyTorch CUDA 12.1 安装成功
    )
) else (
    echo [3/7] 跳过 PyTorch 安装（使用 -Torch 参数安装）
    echo       如需 CUDA 支持: scripts\install.bat -Torch
)

REM ============================================================
REM Step 4: GPT-SoVITS 语音合成依赖 (可选)
REM ============================================================
echo.
if "%INSTALL_GPT_SOVITS%"=="1" (
    echo [4/7] 安装 GPT-SoVITS 语音合成依赖...

    echo   - 安装 HuggingFace 生态...
    "%PYTHON_EXE%" -m pip install "transformers>=4.38.0" huggingface_hub peft %PIP_INDEX_ARGS%

    echo   - 安装深度学习工具...
    "%PYTHON_EXE%" -m pip install pytorch-lightning torchmetrics einops x-transformers %PIP_INDEX_ARGS%

    echo   - 安装音频处理...
    "%PYTHON_EXE%" -m pip install librosa soundfile ffmpeg-python %PIP_INDEX_ARGS%

    echo   - 安装 ONNX 推理...
    "%PYTHON_EXE%" -m pip install onnxruntime %PIP_INDEX_ARGS%

    echo   - 安装中文文本处理...
    "%PYTHON_EXE%" -m pip install pypinyin cn2an %PIP_INDEX_ARGS%

    echo   - 安装 NLP 工具...
    "%PYTHON_EXE%" -m pip install nltk matplotlib %PIP_INDEX_ARGS%

    echo   - 安装 MCP 协议...
    "%PYTHON_EXE%" -m pip install mcp %PIP_INDEX_ARGS%

    echo [OK] GPT-SoVITS 依赖安装完成
) else (
    echo [4/7] 跳过 GPT-SoVITS 依赖（使用 -GptSovits 参数安装）
)

REM ============================================================
REM Step 5: 可选依赖 (可选)
REM ============================================================
echo.
if "%INSTALL_OPTIONAL%"=="1" (
    echo [5/7] 安装可选依赖...

    echo   - 安装 Docker SDK...
    "%PYTHON_EXE%" -m pip install docker %PIP_INDEX_ARGS%

    echo   - 安装 AWS SDK...
    "%PYTHON_EXE%" -m pip install boto3 %PIP_INDEX_ARGS%

    echo   - 安装网页爬取...
    "%PYTHON_EXE%" -m pip install crawl4ai %PIP_INDEX_ARGS%

    echo [OK] 可选依赖安装完成
) else (
    echo [5/7] 跳过可选依赖（使用 -Optional 参数安装）
)

REM ============================================================
REM Step 6: 语言特定依赖提示
REM ============================================================
echo.
echo [6/7] 语言特定依赖（按需手动安装）...
echo   日语 TTS: pip install pyopenjtalk
echo   韩语 TTS: pip install jamo ko_pron g2pk2
echo   英语 G2P: pip install g2p_en wordsegment

REM ============================================================
REM Step 7: 开发环境依赖 (可选)
REM ============================================================
echo.
if "%INSTALL_DEV%"=="1" (
    echo [7/7] 安装开发环境依赖...
    for %%P in (
        "pytest>=7.4.0"
        "pytest-cov>=4.1.0"
        "pytest-asyncio>=0.21.0"
        "pytest-mock>=3.12.0"
        "pytest-xdist>=3.5.0"
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
    echo [7/7] 跳过开发环境依赖（使用 -Dev 参数安装）
)

REM ============================================================
REM Step 8: 检查并构建 C++ 加速引擎
REM ============================================================
echo.
echo [INFO] 检查 C++ 加速引擎...
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
echo.
echo 已安装:
echo   [√] 核心依赖（含 httpx[http2]、h2）
if "%INSTALL_TORCH%"=="1" echo   [√] PyTorch (gt;=2.6.0)
if "%INSTALL_GPT_SOVITS%"=="1" echo   [√] GPT-SoVITS 语音合成
if "%INSTALL_OPTIONAL%"=="1" echo   [√] 可选依赖
if "%INSTALL_DEV%"=="1" echo   [√] 开发/测试依赖
echo.
echo 现在可以运行:
echo   .\scripts\start.bat
echo   或根目录 .\run_with_runtime.bat
echo ============================================

endlocal
exit /b 0
