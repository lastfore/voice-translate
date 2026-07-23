@echo off
REM Slice vocals by LRC lyric timestamps
REM See docs/词曲分离与声乐切片安装指南.md

setlocal EnableDelayedExpansion

set ROOT=D:\code\voice-translate

if "%~1"=="" (
    echo Usage: slice-vocals-lrc.bat ^<lrc_file^> ^<vocals_audio_file^> [output_dir]
    echo Example: slice-vocals-lrc.bat input\test.lrc "output\separated\test_(Vocals)_mel_band_roformer_kim_ft_unwa.flac"
    exit /b 1
)

if "%~2"=="" (
    echo Error: vocals audio file is required.
    exit /b 1
)

set "LRC_FILE=%~1"
set "VOCALS_FILE=%~2"
set "OUTPUT_DIR=%~3"
set "SONG_NAME=%~n1"

call %ROOT%\separator-env\Scripts\activate.bat

if "!OUTPUT_DIR!"=="" (
    python "%ROOT%\scripts\slice-vocals-lrc.py" "!LRC_FILE!" "!VOCALS_FILE!" --song-name "!SONG_NAME!"
) else (
    python "%ROOT%\scripts\slice-vocals-lrc.py" "!LRC_FILE!" "!VOCALS_FILE!" -o "!OUTPUT_DIR!" --song-name "!SONG_NAME!"
)

endlocal
