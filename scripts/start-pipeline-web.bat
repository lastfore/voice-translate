@echo off
REM FastAPI + React Pipeline Web (dev)
REM Starts the API (8000) and Vite frontend (5173) in separate console windows.
REM See docs/管线WebUI迁移对照表-FastAPI-React.md

setlocal
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=

cd /d %~dp0..
set ROOT=%CD%

echo Checking Node.js...
where node >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found. Install Node 18+ and retry.
    exit /b 1
)

if not exist "%ROOT%\frontend\node_modules\" (
    echo Frontend dependencies missing. Running npm install...
    pushd "%ROOT%\frontend"
    call npm install
    if errorlevel 1 (
        popd
        exit /b 1
    )
    popd
)

echo Starting Pipeline API at http://127.0.0.1:8000/ ...
start "Pipeline API" cmd /k call "%ROOT%\scripts\start-pipeline-api.bat"

echo Waiting for API startup...
timeout /t 3 /nobreak >nul

echo Starting React dev server at http://127.0.0.1:5173/ ...
start "Pipeline Frontend" cmd /k "cd /d ""%ROOT%\frontend"" && npm run dev"

echo.
echo Pipeline Web is starting in two console windows:
echo   Frontend  http://127.0.0.1:5173/
echo   API       http://127.0.0.1:8000/health
echo.
echo To stop: scripts\stop-pipeline-web.bat

endlocal
