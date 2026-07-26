@echo off
REM FastAPI Pipeline API (Phase 0+)
REM See docs/管线WebUI迁移对照表-FastAPI-React.md

setlocal
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=

cd /d %~dp0..
set ROOT=%CD%

call "%ROOT%\separator-env\Scripts\activate.bat"

echo Checking FastAPI/uvicorn...
python -c "import fastapi, uvicorn, anyio" 2>nul
if errorlevel 1 (
    echo FastAPI stack not found in separator-env. Installing from requirements-api.txt ...
    where uv >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Install manually: uv pip install --python separator-env\Scripts\python.exe -r requirements-api.txt
        exit /b 1
    )
    uv pip install --python "%ROOT%\separator-env\Scripts\python.exe" -r requirements-api.txt
    if errorlevel 1 exit /b 1
)

REM --workers 1 is mandatory: the GPU job queue is an in-process singleton;
REM multiple worker processes would each get their own queue and break
REM single-GPU serialization (see docs §4.4 / §11).
echo Starting Pipeline API at http://127.0.0.1:8000/  (--workers 1, required)
uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 1

endlocal
