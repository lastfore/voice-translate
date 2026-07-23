@echo off
REM Unified Pipeline Web UI
REM See docs/管线WebUI设计方案.md

setlocal
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=

cd /d %~dp0..
set ROOT=%CD%

call "%ROOT%\separator-env\Scripts\activate.bat"

echo Checking Gradio...
python -c "import gradio" 2>nul
if errorlevel 1 (
    echo Gradio not found in separator-env. Installing gradio==5.23.0 ...
    where uv >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Install gradio manually: uv pip install --python separator-env\Scripts\python.exe gradio==5.23.0
        exit /b 1
    )
    uv pip install --python "%ROOT%\separator-env\Scripts\python.exe" "gradio==5.23.0"
    if errorlevel 1 exit /b 1
)

echo Starting Pipeline Web UI at http://127.0.0.1:7860/
python -m webui.pipeline_app

endlocal
