@echo off
REM One-shot pipeline: separate audio + slice vocals by LRC
REM See docs/词曲分离与声乐切片安装指南.md

setlocal EnableDelayedExpansion

set ROOT=D:\code\voice-translate
set MODEL_DIR=%ROOT%\separator-env\models\audio-separator

if "%~1"=="" (
    echo Usage: process-song.bat ^<input_audio_file^> [lrc_file]
    echo Example: process-song.bat input\test.flac
    echo          process-song.bat input\test.flac input\test.lrc
    exit /b 1
)

set "INPUT_AUDIO=%~1"
set "SONG_NAME=%~n1"
set "LRC_FILE=%~2"

if "!LRC_FILE!"=="" (
    set "LRC_FILE=%~dp1!SONG_NAME!.lrc"
)

if not exist "!INPUT_AUDIO!" (
    echo Error: input audio not found: !INPUT_AUDIO!
    exit /b 1
)

if not exist "!LRC_FILE!" (
    echo Error: LRC file not found: !LRC_FILE!
    exit /b 1
)

echo === Step 1/2: Audio separation ===
call "%ROOT%\scripts\separate-audio.bat" "!INPUT_AUDIO!"
if errorlevel 1 (
    echo Step 1 failed: audio separation
    exit /b 1
)

set "VOCALS_FILE=%ROOT%\output\separated\!SONG_NAME!_(vocals)_mel_band_roformer_kim_ft_unwa.flac"
if not exist "!VOCALS_FILE!" (
    echo Error: expected vocals file not found: !VOCALS_FILE!
    exit /b 1
)
echo Vocals file: !VOCALS_FILE!

echo.
echo === Step 2/2: LRC vocal slicing ===
call "%ROOT%\scripts\slice-vocals-lrc.bat" "!LRC_FILE!" "!VOCALS_FILE!"
if errorlevel 1 (
    echo Step 2 failed: LRC slicing
    exit /b 1
)

echo.
echo Done.
echo Separated: %ROOT%\output\separated\
echo Slices:    %ROOT%\output\slices\!SONG_NAME!\
endlocal
