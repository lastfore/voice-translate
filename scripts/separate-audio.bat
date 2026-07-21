@echo off
REM Audio separation script (MelBand-RoFormer)
REM See docs/词曲分离与声乐切片安装指南.md

setlocal

set ROOT=D:\code\voice-translate
set MODEL_DIR=%ROOT%\separator-env\models\audio-separator
set TORCH_HOME=%ROOT%\separator-env\models\torch-hub
set HF_HOME=%ROOT%\separator-env\models\hf-cache
set AUDIO_SEPARATOR_MODEL_DIR=%MODEL_DIR%

if "%~1"=="" (
    echo Usage: separate-audio.bat ^<input_audio_file^>
    echo Example: separate-audio.bat input\song.flac
    exit /b 1
)

if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"
if not exist "%ROOT%\output\separated" mkdir "%ROOT%\output\separated"

call %ROOT%\separator-env\Scripts\activate.bat

python "%ROOT%\scripts\verify-separator-model.py"
if errorlevel 1 (
    echo.
    echo Model checkpoint is missing or corrupted.
    echo Run: scripts\repair-separator-model.bat
    exit /b 1
)

echo Separating: %~1
echo Model cache: %MODEL_DIR%
echo Output dir:  %ROOT%\output\separated

audio-separator "%~1" ^
  --model_filename mel_band_roformer_kim_ft_unwa.ckpt ^
  --model_file_dir "%MODEL_DIR%" ^
  --output_format flac ^
  --output_dir "%ROOT%\output\separated"

if errorlevel 1 (
    echo Separation failed.
    exit /b 1
)

echo Done. Output: %ROOT%\output\separated
endlocal
