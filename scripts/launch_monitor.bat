@echo off
setlocal
if not defined PROJECT_LOCAL_PYTHON (
    echo [ERROR] PROJECT_LOCAL_PYTHON is not set
    pause
    exit /b 1
)
cd /d "%~dp0.."
if defined PYTHONPATH set "PYTHONPATH=%PYTHONPATH%"
"%PROJECT_LOCAL_PYTHON%" microservices\monitor_panel.py
endlocal
