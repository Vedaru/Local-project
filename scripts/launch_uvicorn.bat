@echo off
REM Called from start.bat in a new window; requires PROJECT_LOCAL_PYTHON (absolute path)
setlocal
if not defined PROJECT_LOCAL_PYTHON (
    echo [ERROR] PROJECT_LOCAL_PYTHON is not set
    pause
    exit /b 1
)
if not exist "%PROJECT_LOCAL_PYTHON%" (
    echo [ERROR] Python not found: %PROJECT_LOCAL_PYTHON%
    pause
    exit /b 1
)
set "UVICORN_APP=%~1"
set "UVICORN_PORT=%~2"
if "%UVICORN_APP%"=="" (
    echo [ERROR] Missing uvicorn app module argument
    pause
    exit /b 1
)
if "%UVICORN_PORT%"=="" (
    echo [ERROR] Missing port argument
    pause
    exit /b 1
)
cd /d "%~dp0.."
if defined PYTHONPATH set "PYTHONPATH=%PYTHONPATH%"
"%PROJECT_LOCAL_PYTHON%" -m uvicorn %UVICORN_APP% --host 127.0.0.1 --port %UVICORN_PORT%
endlocal
