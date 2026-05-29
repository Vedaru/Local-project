@echo off
REM Project Local - Runtime Launcher
REM 使用独立的 Python Runtime 启动项目

setlocal
chcp 65001 >nul

set "START_SERVICES_ONLY=0"
if /I "%~1"=="--start-services-only" (
    set "START_SERVICES_ONLY=1"
    shift
)

pushd "%~dp0.."
set "PROJECT_DIR=%CD%\"
popd
set "RUNTIME_DIR=%PROJECT_DIR%runtime"
set "PYTHON_EXE=%RUNTIME_DIR%\python.exe"

REM 检查 runtime Python 是否存在
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

REM 设置环境变量
set "CT2_USE_CUDA=0"
if not defined LOKY_MAX_CPU_COUNT (
    if defined NUMBER_OF_PROCESSORS (
        set "LOKY_MAX_CPU_COUNT=%NUMBER_OF_PROCESSORS%"
    ) else (
        set "LOKY_MAX_CPU_COUNT=4"
    )
)

REM 切换到项目目录
cd /d "%PROJECT_DIR%"

if "%START_SERVICES_ONLY%"=="1" (
    echo [INFO] 仅启动微服务栈模式
    call :start_microservices_stack
    set "_EC=%ERRORLEVEL%"
    endlocal & exit /b %_EC%
)

echo ============================================
echo Project Local - 使用独立 Runtime 启动
echo ============================================
echo Python: %PYTHON_EXE%
echo 项目目录: %PROJECT_DIR%
echo ============================================
echo.

if "%MICROSERVICES_GATEWAY_URL%"=="" set "MICROSERVICES_GATEWAY_URL=http://127.0.0.1:18080"
set "_GW_OPENAPI_URL=%MICROSERVICES_GATEWAY_URL%/openapi.json"

echo [INFO] 检查微服务网关状态: %_GW_OPENAPI_URL%
"%PYTHON_EXE%" -c "import sys,urllib.request;u='%_GW_OPENAPI_URL%';r=urllib.request.urlopen(u,timeout=2);b=r.read().decode('utf-8','ignore');ok=(200<=getattr(r,'status',200)<300 and '/v1/status/services' in b and '/v1/chat' in b);sys.exit(0 if ok else 1)" >nul 2>&1

if errorlevel 1 (
    echo [WARN] 网关不可用，正在自动启动微服务栈...
    call :start_microservices_stack
    call :wait_gateway_ready

    if "%_GW_READY%"=="0" (
        echo [WARN] 默认端口未就绪，尝试备用端口组: 18080/19080/28080 ...

        call :set_ports_from_base 18080
        call :start_microservices_stack
        call :wait_gateway_ready

        if "%_GW_READY%"=="0" (
            call :set_ports_from_base 19080
            call :start_microservices_stack
            call :wait_gateway_ready
        )

        if "%_GW_READY%"=="0" (
            call :set_ports_from_base 28080
            call :start_microservices_stack
            call :wait_gateway_ready
        )

        if "%_GW_READY%"=="0" (
            echo [错误] 网关启动超时，请检查微服务窗口日志后重试。
            pause
            exit /b 1
        )
    )
) else (
    echo [INFO] 网关已就绪。
)

echo [INFO] 检查运行时核心依赖...
"%PYTHON_EXE%" -c "import importlib.util,sys;mods=['PyQt6','PyQt6.QtWebEngineWidgets','qasync','openai','fastapi','uvicorn','httpx','pydantic','dotenv','yaml','requests'];miss=[m for m in mods if importlib.util.find_spec(m) is None];sys.exit(0 if not miss else 1)" >nul 2>&1
if errorlevel 1 (
    echo [WARN] 检测到缺少核心依赖，正在补装最小运行集...
    "%PYTHON_EXE%" -m pip install openai python-dotenv pyyaml requests qasync fastapi uvicorn httpx pydantic PyQt6 PyQt6-WebEngine
    if errorlevel 1 (
        echo [错误] 自动安装核心依赖失败，请手动执行 scripts\install.bat
        pause
        exit /b 1
    )
)

REM 启动主程序
set "ENTRY_SCRIPT=%PROJECT_DIR%main.py"
if not exist "%ENTRY_SCRIPT%" (
    echo [错误] 未找到可启动入口（main.py）。
    pause
    exit /b 1
)
"%PYTHON_EXE%" "%ENTRY_SCRIPT%" %*

if errorlevel 1 (
    echo.
    echo [错误] 程序执行失败，错误代码: %errorlevel%
    pause
)

endlocal
goto :eof

:start_microservices_stack
set "PYTHONPATH=%PROJECT_DIR%"

if "%GATEWAY_PORT%"=="" set "GATEWAY_PORT=18080"
if "%ORCHESTRATOR_PORT%"=="" set "ORCHESTRATOR_PORT=18081"
if "%MEMORY_SERVICE_PORT%"=="" set "MEMORY_SERVICE_PORT=18082"
if "%AGENT_SERVICE_PORT%"=="" set "AGENT_SERVICE_PORT=18083"
if "%VOICE_SERVICE_PORT%"=="" set "VOICE_SERVICE_PORT=18084"

set "ORCHESTRATOR_URL=http://127.0.0.1:%ORCHESTRATOR_PORT%"
set "MEMORY_SERVICE_URL=http://127.0.0.1:%MEMORY_SERVICE_PORT%"
set "AGENT_SERVICE_URL=http://127.0.0.1:%AGENT_SERVICE_PORT%"
set "VOICE_SERVICE_URL=http://127.0.0.1:%VOICE_SERVICE_PORT%"

echo [INFO] Starting microservices in separate windows...

start "memory-service" cmd /k "cd /d %PROJECT_DIR% && set PYTHONPATH=%PYTHONPATH% && %PYTHON_EXE% -m uvicorn microservices.memory_service.main:app --host 127.0.0.1 --port %MEMORY_SERVICE_PORT%"
start "agent-service" cmd /k "cd /d %PROJECT_DIR% && set PYTHONPATH=%PYTHONPATH% && %PYTHON_EXE% -m uvicorn microservices.agent_service.main:app --host 127.0.0.1 --port %AGENT_SERVICE_PORT%"
start "voice-service" cmd /k "cd /d %PROJECT_DIR% && set PYTHONPATH=%PYTHONPATH% && %PYTHON_EXE% -m uvicorn microservices.voice_service.main:app --host 127.0.0.1 --port %VOICE_SERVICE_PORT%"
start "orchestrator" cmd /k "cd /d %PROJECT_DIR% && set PYTHONPATH=%PYTHONPATH% && set MEMORY_SERVICE_URL=%MEMORY_SERVICE_URL% && set AGENT_SERVICE_URL=%AGENT_SERVICE_URL% && set VOICE_SERVICE_URL=%VOICE_SERVICE_URL% && %PYTHON_EXE% -m uvicorn microservices.orchestrator.main:app --host 127.0.0.1 --port %ORCHESTRATOR_PORT%"
start "gateway" cmd /k "cd /d %PROJECT_DIR% && set PYTHONPATH=%PYTHONPATH% && set GATEWAY_BIND_HOST=127.0.0.1 && set GATEWAY_PORT=%GATEWAY_PORT% && set ORCHESTRATOR_URL=%ORCHESTRATOR_URL% && set MEMORY_SERVICE_URL=%MEMORY_SERVICE_URL% && set AGENT_SERVICE_URL=%AGENT_SERVICE_URL% && set VOICE_SERVICE_URL=%VOICE_SERVICE_URL% && %PYTHON_EXE% -m uvicorn microservices.gateway.main:app --host 127.0.0.1 --port %GATEWAY_PORT%"

timeout /t 2 >nul

echo [INFO] Starting monitor panel...
start "monitor-panel" cmd /k "cd /d %PROJECT_DIR% && set PYTHONPATH=%PYTHONPATH% && set GATEWAY_PORT=%GATEWAY_PORT% && set ORCHESTRATOR_PORT=%ORCHESTRATOR_PORT% && set MEMORY_SERVICE_PORT=%MEMORY_SERVICE_PORT% && set AGENT_SERVICE_PORT=%AGENT_SERVICE_PORT% && set VOICE_SERVICE_PORT=%VOICE_SERVICE_PORT% && %PYTHON_EXE% microservices\monitor_panel.py"

echo [DONE] Services are launching.
echo        Gateway: http://127.0.0.1:%GATEWAY_PORT%/health
echo        Aggregated status: http://127.0.0.1:%GATEWAY_PORT%/v1/status/services
exit /b 0

:set_ports_from_base
set "GATEWAY_PORT=%~1"
set /a ORCHESTRATOR_PORT=%~1+1
set /a MEMORY_SERVICE_PORT=%~1+2
set /a AGENT_SERVICE_PORT=%~1+3
set /a VOICE_SERVICE_PORT=%~1+4
set "MICROSERVICES_GATEWAY_URL=http://127.0.0.1:%GATEWAY_PORT%"
set "_GW_OPENAPI_URL=%MICROSERVICES_GATEWAY_URL%/openapi.json"
echo [INFO] 切换到端口组: %GATEWAY_PORT%/%ORCHESTRATOR_PORT%/%MEMORY_SERVICE_PORT%/%AGENT_SERVICE_PORT%/%VOICE_SERVICE_PORT%
exit /b 0

:wait_gateway_ready
set "_GW_READY=0"
for /l %%N in (1,1,20) do (
    "%PYTHON_EXE%" -c "import sys,urllib.request;u='%_GW_OPENAPI_URL%';r=urllib.request.urlopen(u,timeout=2);b=r.read().decode('utf-8','ignore');ok=(200<=getattr(r,'status',200)<300 and '/v1/status/services' in b and '/v1/chat' in b);sys.exit(0 if ok else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "_GW_READY=1"
        exit /b 0
    )
    timeout /t 1 >nul
)
exit /b 0

