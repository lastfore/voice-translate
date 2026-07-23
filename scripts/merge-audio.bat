@echo off
REM Merge converted vocals with instrumental backing
REM See docs/人声伴奏结合安装指南.md

setlocal EnableDelayedExpansion

set ROOT=D:\code\voice-translate
set MODEL_DIR=%ROOT%\separator-env\models\audio-separator
set AUDIO_SEPARATOR_MODEL_DIR=%MODEL_DIR%

if "%~1"=="" goto usage

if not exist "%ROOT%\output\merged" mkdir "%ROOT%\output\merged"

call %ROOT%\separator-env\Scripts\activate.bat

set "PY_ARGS="
:parse_args
if "%~1"=="" goto run_merge
if /i "%~1"=="--vocals" goto arg_vocals
if /i "%~1"=="--instrumental" goto arg_instrumental
if /i "%~1"=="--reference" goto arg_reference
if /i "%~1"=="--original-vocals" goto arg_original_vocals
if /i "%~1"=="--manifest" goto arg_manifest
if /i "%~1"=="--slices-dir" goto arg_slices_dir
if /i "%~1"=="-o" goto arg_output_dir
if /i "%~1"=="--output-dir" goto arg_output_dir
if /i "%~1"=="--model-dir" goto arg_model_dir
if /i "%~1"=="--profile" goto arg_profile
if /i "%~1"=="--vocals-gain" goto arg_vocals_gain
if /i "%~1"=="--instrumental-gain" goto arg_instrumental_gain
set "PY_ARGS=!PY_ARGS! %~1"
shift
goto parse_args

:arg_vocals
set "PY_ARGS=!PY_ARGS! --vocals "%~2""
shift
shift
goto parse_args

:arg_instrumental
set "PY_ARGS=!PY_ARGS! --instrumental "%~2""
shift
shift
goto parse_args

:arg_reference
set "PY_ARGS=!PY_ARGS! --reference "%~2""
shift
shift
goto parse_args

:arg_original_vocals
set "PY_ARGS=!PY_ARGS! --original-vocals "%~2""
shift
shift
goto parse_args

:arg_manifest
set "PY_ARGS=!PY_ARGS! --manifest "%~2""
shift
shift
goto parse_args

:arg_slices_dir
set "PY_ARGS=!PY_ARGS! --slices-dir "%~2""
shift
shift
goto parse_args

:arg_output_dir
set "PY_ARGS=!PY_ARGS! -o "%~2""
shift
shift
goto parse_args

:arg_model_dir
set "PY_ARGS=!PY_ARGS! --model-dir "%~2""
shift
shift
goto parse_args

:arg_profile
set "PY_ARGS=!PY_ARGS! --profile %~2"
shift
shift
goto parse_args

:arg_vocals_gain
set "PY_ARGS=!PY_ARGS! --vocals-gain %~2"
shift
shift
goto parse_args

:arg_instrumental_gain
set "PY_ARGS=!PY_ARGS! --instrumental-gain %~2"
shift
shift
goto parse_args

:run_merge
python "%ROOT%\scripts\merge-audio.py" !PY_ARGS!

if errorlevel 1 (
    echo Merge failed.
    exit /b 1
)

echo Done. Output: %ROOT%\output\merged
endlocal
exit /b 0

:usage
echo Usage: merge-audio.bat --vocals ^<converted_vocals^> --instrumental ^<instrumental.flac^> [options]
echo Example: merge-audio.bat --vocals output\converted\song.flac --instrumental "output\separated\song_(Instrumental)_mel_band_roformer_kim_ft_unwa.flac" --reference input\song.flac
exit /b 1
