@echo off
REM Project Local launcher - ASCII-only batch (use runtime\python.exe)
setlocal EnableExtensions EnableDelayedExpansion

set "START_SERVICES_ONLY=0"
if /I "%~1"=="--start-services-only" set "START_SERVICES_ONLY=1"

pushd "%~dp0"
cd ..
set "PROJECT_DIR=%CD%\"
popd
if not exist "%PROJECT_DIR%main.py" (
    echo [ERROR] Invalid project dir: %PROJECT_DIR%
    echo Run from repo root via run_with_runtime.bat or scripts\start.bat
    pause
    exit /b 1
)
set "RUNTIME_DIR=%PROJECT_DIR%runtime"
set "PYTHON_EXE=%RUNTIME_DIR%\python.exe"

if not "%PROJECT_PYTHON%"=="" (
    set "PYTHON_EXE=%PROJECT_PYTHON%"
    echo [INFO] Using PROJECT_PYTHON=%PYTHON_EXE%
) else if not exist "%PYTHON_EXE%" (
    echo [ERROR] Missing runtime\python.exe
    echo Run: scripts\setup_runtime.bat
    echo Then: scripts\install.bat
    pause
    exit /b 1
)

call :resolve_python_absolute
if errorlevel 1 (
    echo [ERROR] Cannot resolve Python executable path
    pause
    exit /b 1
)
set "PROJECT_LOCAL_PYTHON=%PYTHON_EXE%"
echo [INFO] Python for GUI and microservices: %PYTHON_EXE%

set "CT2_USE_CUDA=0"
set "PYTHONNOUSERSITE=1"
if not defined LOKY_MAX_CPU_COUNT (
    if defined NUMBER_OF_PROCESSORS (
        set "LOKY_MAX_CPU_COUNT=%NUMBER_OF_PROCESSORS%"
    ) else (
        set "LOKY_MAX_CPU_COUNT=4"
    )
)

cd /d "%PROJECT_DIR%"

if "%START_SERVICES_ONLY%"=="1" (
    echo [INFO] Microservices-only mode
    call :start_microservices_stack
    set "_EC=%ERRORLEVEL%"
    endlocal & exit /b %_EC%
)

echo ============================================
echo Project Local - starting with runtime
echo ============================================
echo Python: %PYTHON_EXE%
echo Project: %PROJECT_DIR%
echo ============================================
echo.

if "%MICROSERVICES_GATEWAY_URL%"=="" set "MICROSERVICES_GATEWAY_URL=http://127.0.0.1:18080"
set "_GW_OPENAPI_URL=%MICROSERVICES_GATEWAY_URL%/openapi.json"

echo [INFO] Checking gateway: %_GW_OPENAPI_URL%
"%PYTHON_EXE%" -c "import sys,urllib.request;u='%_GW_OPENAPI_URL%';r=urllib.request.urlopen(u,timeout=2);b=r.read().decode('utf-8','ignore');ok=(200<=getattr(r,'status',200)<300 and '/v1/status/services' in b and '/v1/chat' in b);sys.exit(0 if ok else 1)" >nul 2>&1
set "_GW_EC=!ERRORLEVEL!"

if not "!_GW_EC!"=="0" goto :start_microservices
echo [INFO] Gateway is ready.
goto :check_core_deps

:start_microservices
echo [WARN] Gateway not ready, starting microservices...
call :start_microservices_stack
call :wait_gateway_ready

if not "!_GW_READY!"=="0" goto :check_core_deps
echo [WARN] Default ports not ready, trying 18080 / 19080 / 28080...

call :set_ports_from_base 18080
call :start_microservices_stack
call :wait_gateway_ready

if not "!_GW_READY!"=="0" goto :check_core_deps
call :set_ports_from_base 19080
call :start_microservices_stack
call :wait_gateway_ready

if not "!_GW_READY!"=="0" goto :check_core_deps
call :set_ports_from_base 28080
call :start_microservices_stack
call :wait_gateway_ready

if "!_GW_READY!"=="0" (
    echo [ERROR] Gateway startup timed out. Check microservice window logs.
    pause
    exit /b 1
)

:check_core_deps

echo [INFO] Checking core dependencies...
"%PYTHON_EXE%" -c "import importlib.util,sys;mods=['PyQt6','PyQt6.QtWebEngineWidgets','qasync','openai','fastapi','uvicorn','httpx','pydantic','dotenv','yaml','requests'];miss=[m for m in mods if importlib.util.find_spec(m) is None];sys.exit(0 if not miss else 1)" >nul 2>&1
set "_CD_EC=%ERRORLEVEL%"
if not "%_CD_EC%"=="0" (
    echo [WARN] Missing packages, installing minimal set...
    "%PYTHON_EXE%" -m pip install openai python-dotenv pyyaml requests qasync httpx pydantic PyQt6 PyQt6-WebEngine "fastapi>=0.128.6,<0.136" "uvicorn[standard]>=0.34.0,<0.37"
    set "_PI_EC=!ERRORLEVEL!"
    if not "!_PI_EC!"=="0" (
        echo [ERROR] Auto-install failed. Run scripts\install.bat
        pause
        exit /b 1
    )
)

set "ENTRY_SCRIPT=%PROJECT_DIR%main.py"
if not exist "%ENTRY_SCRIPT%" (
    echo [ERROR] Entry not found: main.py
    pause
    exit /b 1
)
"%PYTHON_EXE%" "%ENTRY_SCRIPT%" %*
set "_MAIN_EC=%ERRORLEVEL%"

if not "%_MAIN_EC%"=="0" (
    echo.
    echo [ERROR] Application failed, exit code: %_MAIN_EC%
    pause
)

endlocal & exit /b %_MAIN_EC%

:resolve_python_absolute
for /f "delims=" %%i in ('"%PYTHON_EXE%" -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%i"
if not exist "%PYTHON_EXE%" exit /b 1
exit /b 0

:start_microservices_stack
set "PYTHONPATH=%PROJECT_DIR%"
set "PROJECT_LOCAL_PYTHON=%PYTHON_EXE%"

echo [INFO] Python for microservices: %PYTHON_EXE%
echo [INFO] Verifying FastAPI/Starlette stack...
"%PYTHON_EXE%" "%PROJECT_DIR%scripts\ensure_microservice_deps.py"
if not errorlevel 1 goto :preflight_ok
echo [ERROR] FastAPI/Starlette preflight failed (see log above)
echo [HINT] Install deps first: scripts\install.bat
echo        Or: "%PYTHON_EXE%" -m pip install "fastapi>=0.128.6,<0.136" "uvicorn[standard]>=0.34.0,<0.37"
pause
exit /b 1
:preflight_ok

if not defined NO_PROXY set "NO_PROXY=127.0.0.1,localhost,::1"
if not defined no_proxy set "no_proxy=%NO_PROXY%"

if "%GATEWAY_PORT%"=="" set "GATEWAY_PORT=18080"
if "%ORCHESTRATOR_PORT%"=="" set "ORCHESTRATOR_PORT=18081"
if "%MEMORY_SERVICE_PORT%"=="" set "MEMORY_SERVICE_PORT=18082"
if "%AGENT_SERVICE_PORT%"=="" set "AGENT_SERVICE_PORT=18083"
if "%VOICE_SERVICE_PORT%"=="" set "VOICE_SERVICE_PORT=18084"

set "ORCHESTRATOR_URL=http://127.0.0.1:%ORCHESTRATOR_PORT%"
set "MEMORY_SERVICE_URL=http://127.0.0.1:%MEMORY_SERVICE_PORT%"
set "AGENT_SERVICE_URL=http://127.0.0.1:%AGENT_SERVICE_PORT%"
set "VOICE_SERVICE_URL=http://127.0.0.1:%VOICE_SERVICE_PORT%"

set "LAUNCH_ROOT=%PROJECT_DIR%"
if "%LAUNCH_ROOT:~-1%"=="\" set "LAUNCH_ROOT=%LAUNCH_ROOT:~0,-1%"

echo [INFO] Starting microservices in separate windows...

start "memory-service" cmd /k cd /d "%LAUNCH_ROOT%" ^&^& set "PROJECT_LOCAL_PYTHON=%PROJECT_LOCAL_PYTHON%" ^&^& set "PYTHONPATH=%LAUNCH_ROOT%" ^&^& call scripts\launch_uvicorn.bat microservices.memory_service.main:app %MEMORY_SERVICE_PORT%
echo [INFO] Installing agent runtime dependencies (mcp, search, browser-use)...
"%PYTHON_EXE%" -m pip install -q "mcp>=1.0.0" "baidusearch==1.0.3" "duckduckgo_search==3.9.6" "tenacity==8.2.3" "loguru==0.7.2" "browser-use==0.1.40" >nul 2>&1

start "agent-service" cmd /k cd /d "%LAUNCH_ROOT%" ^&^& set "PROJECT_LOCAL_PYTHON=%PROJECT_LOCAL_PYTHON%" ^&^& set "PYTHONPATH=%LAUNCH_ROOT%" ^&^& call scripts\launch_uvicorn.bat microservices.agent_service.main:app %AGENT_SERVICE_PORT%
start "voice-service" cmd /k cd /d "%LAUNCH_ROOT%" ^&^& set "PROJECT_LOCAL_PYTHON=%PROJECT_LOCAL_PYTHON%" ^&^& set "PYTHONPATH=%LAUNCH_ROOT%" ^&^& call scripts\launch_uvicorn.bat microservices.voice_service.main:app %VOICE_SERVICE_PORT%
start "orchestrator" cmd /k cd /d "%LAUNCH_ROOT%" ^&^& set "PROJECT_LOCAL_PYTHON=%PROJECT_LOCAL_PYTHON%" ^&^& set "PYTHONPATH=%LAUNCH_ROOT%" ^&^& set "MEMORY_SERVICE_URL=%MEMORY_SERVICE_URL%" ^&^& set "AGENT_SERVICE_URL=%AGENT_SERVICE_URL%" ^&^& set "VOICE_SERVICE_URL=%VOICE_SERVICE_URL%" ^&^& call scripts\launch_uvicorn.bat microservices.orchestrator.main:app %ORCHESTRATOR_PORT%
start "gateway" cmd /k cd /d "%LAUNCH_ROOT%" ^&^& set "PROJECT_LOCAL_PYTHON=%PROJECT_LOCAL_PYTHON%" ^&^& set "PYTHONPATH=%LAUNCH_ROOT%" ^&^& set "GATEWAY_BIND_HOST=127.0.0.1" ^&^& set "GATEWAY_PORT=%GATEWAY_PORT%" ^&^& set "ORCHESTRATOR_URL=%ORCHESTRATOR_URL%" ^&^& set "MEMORY_SERVICE_URL=%MEMORY_SERVICE_URL%" ^&^& set "AGENT_SERVICE_URL=%AGENT_SERVICE_URL%" ^&^& set "VOICE_SERVICE_URL=%VOICE_SERVICE_URL%" ^&^& call scripts\launch_uvicorn.bat microservices.gateway.main:app %GATEWAY_PORT%

echo [INFO] Waiting for voice-service /health/live (max ~120s)...
cd /d "%PROJECT_DIR%"
"%PYTHON_EXE%" scripts\wait_voice_health.py --port %VOICE_SERVICE_PORT% --max-wait 120 --interval 1
set "_VH_EC=!ERRORLEVEL!"
if not "!_VH_EC!"=="0" (
    echo [WARN] voice-service not ready in 120s; monitor may show DOWN briefly
)

echo [INFO] Starting monitor panel...
start "monitor-panel" cmd /k cd /d "%LAUNCH_ROOT%" ^&^& set "PROJECT_LOCAL_PYTHON=%PROJECT_LOCAL_PYTHON%" ^&^& set "PYTHONPATH=%LAUNCH_ROOT%" ^&^& set "GATEWAY_PORT=%GATEWAY_PORT%" ^&^& set "ORCHESTRATOR_PORT=%ORCHESTRATOR_PORT%" ^&^& set "MEMORY_SERVICE_PORT=%MEMORY_SERVICE_PORT%" ^&^& set "AGENT_SERVICE_PORT=%AGENT_SERVICE_PORT%" ^&^& set "VOICE_SERVICE_PORT=%VOICE_SERVICE_PORT%" ^&^& call scripts\launch_monitor.bat

echo [DONE] Services are launching.
echo        Gateway: http://127.0.0.1:%GATEWAY_PORT%/health
echo        Status: http://127.0.0.1:%GATEWAY_PORT%/v1/status/services
exit /b 0

:set_ports_from_base
set "GATEWAY_PORT=%~1"
set /a ORCHESTRATOR_PORT=%~1+1
set /a MEMORY_SERVICE_PORT=%~1+2
set /a AGENT_SERVICE_PORT=%~1+3
set /a VOICE_SERVICE_PORT=%~1+4
set "MICROSERVICES_GATEWAY_URL=http://127.0.0.1:%GATEWAY_PORT%"
set "_GW_OPENAPI_URL=%MICROSERVICES_GATEWAY_URL%/openapi.json"
echo [INFO] Port group: %GATEWAY_PORT%/%ORCHESTRATOR_PORT%/%MEMORY_SERVICE_PORT%/%AGENT_SERVICE_PORT%/%VOICE_SERVICE_PORT%
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
