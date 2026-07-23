@echo off
REM Merge converted vocals with instrumental backing
REM See docs/人声伴奏结合安装指南.md

setlocal

set ROOT=D:\code\voice-translate
set MODEL_DIR=%ROOT%\separator-env\models\audio-separator
set AUDIO_SEPARATOR_MODEL_DIR=%MODEL_DIR%

if "%~1"=="" (
    echo Usage: merge-audio.bat --vocals ^<converted_vocals^> --instrumental ^<instrumental.flac^> [options]
    echo Example: merge-audio.bat --vocals output\converted\song.flac --instrumental output\separated\song_(Instrumental)_mel_band_roformer_kim_ft_unwa.flac --reference input\song.flac
    exit /b 1
)

if not exist "%ROOT%\output\merged" mkdir "%ROOT%\output\merged"

call %ROOT%\separator-env\Scripts\activate.bat

python "%ROOT%\scripts\merge-audio.py" %*

if errorlevel 1 (
    echo Merge failed.
    exit /b 1
)

echo Done. Output: %ROOT%\output\merged
endlocal
