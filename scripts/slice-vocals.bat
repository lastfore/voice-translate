@echo off
REM Vocal phrase slicing with Silero VAD
REM See docs/词曲分离与声乐切片安装指南.md

setlocal EnableDelayedExpansion

set ROOT=D:\code\voice-translate
set TORCH_HOME=%ROOT%\separator-env\models\torch-hub
set HF_HOME=%ROOT%\separator-env\models\hf-cache

if "%~1"=="" (
    echo Usage: slice-vocals.bat ^<vocals_audio_file^> [output_dir]
    echo Example: slice-vocals.bat "output\separated\test_(vocals)_mel_band_roformer_kim_ft_unwa.flac"
    exit /b 1
)

if not exist "%ROOT%\separator-env\models\torch-hub" mkdir "%ROOT%\separator-env\models\torch-hub"

set "VOCALS_FILE=%~1"
set "OUTPUT_DIR=%~2"

call %ROOT%\separator-env\Scripts\activate.bat

if "!OUTPUT_DIR!"=="" (
    python "%ROOT%\scripts\slice-vocals.py" "!VOCALS_FILE!"
) else (
    python "%ROOT%\scripts\slice-vocals.py" "!VOCALS_FILE!" -o "!OUTPUT_DIR!"
)

endlocal
