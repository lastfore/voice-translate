@echo off
REM Batch voice conversion for vocal slices using Seed-VC
REM See docs/Seed-VC安装指南.md

setlocal EnableDelayedExpansion

set ROOT=D:\code\voice-translate
set HF_ENDPOINT=
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost

if "%~1"=="" (
    echo Usage: convert-slices.bat ^<slices_dir^> [options passed to convert-slices.py]
    echo Example: convert-slices.bat output\slices\test
    echo          convert-slices.bat output\slices\test --limit 1
    exit /b 1
)

call %ROOT%\seed-vc-env\Scripts\activate.bat
python "%ROOT%\scripts\convert-slices.py" %*

endlocal
