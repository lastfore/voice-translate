@echo off
REM Stop FastAPI + React Pipeline Web (API 8000, Vite 5173)
REM See docs/管线WebUI迁移对照表-FastAPI-React.md

setlocal enabledelayedexpansion
set FOUND=0

call :kill_port 8000 "Pipeline API"
call :kill_port 5173 "Pipeline Frontend"

if !FOUND!==0 (
    echo No Pipeline Web process listening on 127.0.0.1:8000 or 127.0.0.1:5173.
) else (
    echo Pipeline Web stopped.
)

endlocal
exit /b 0

:kill_port
set PORT=%~1
set LABEL=%~2
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "127.0.0.1:%PORT%" ^| findstr "LISTENING"') do (
    echo Stopping %LABEL% on port %PORT%, PID %%a ...
    taskkill /PID %%a /T /F >nul 2>&1
    if errorlevel 1 (
        echo Failed to stop PID %%a
    ) else (
        echo Stopped.
        set FOUND=1
    )
)
goto :eof
