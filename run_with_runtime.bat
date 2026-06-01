@echo off
REM Launch from project root (double-click this file)
cd /d "%~dp0"
call "%~dp0scripts\start.bat" %*
set "_EC=%ERRORLEVEL%"
if not "%_EC%"=="0" (
    echo.
    echo [ERROR] Start failed, exit code: %_EC%
    pause
)
exit /b %_EC%
