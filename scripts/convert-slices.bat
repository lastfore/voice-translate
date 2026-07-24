@echo off

REM Batch voice conversion for vocal slices using Seed-VC

REM See docs/Seed-VC安装指南.md



setlocal EnableDelayedExpansion



set ROOT=D:\code\voice-translate

set HF_ENDPOINT=

set NO_PROXY=127.0.0.1,localhost

set no_proxy=127.0.0.1,localhost



if "%~1"=="" goto usage



call %ROOT%\seed-vc-env\Scripts\activate.bat



set "SLICES_DIR=%~1"

shift



set "PY_ARGS= "!SLICES_DIR!""

:parse_args

if "%~1"=="" goto run_convert

if /i "%~1"=="--reference" goto arg_reference

if /i "%~1"=="--output" goto arg_output

if /i "%~1"=="--manifest" goto arg_manifest

if /i "%~1"=="--diffusion-steps" goto arg_diffusion_steps

if /i "%~1"=="--length-adjust" goto arg_length_adjust

if /i "%~1"=="--inference-cfg-rate" goto arg_inference_cfg_rate

if /i "%~1"=="--semi-tone-shift" goto arg_semi_tone_shift

if /i "%~1"=="--limit" goto arg_limit

set "PY_ARGS=!PY_ARGS! %~1"

shift

goto parse_args



:arg_reference

set "PY_ARGS=!PY_ARGS! --reference "%~2""

shift

shift

goto parse_args



:arg_output

set "PY_ARGS=!PY_ARGS! --output "%~2""

shift

shift

goto parse_args



:arg_manifest

set "PY_ARGS=!PY_ARGS! --manifest "%~2""

shift

shift

goto parse_args



:arg_diffusion_steps

set "PY_ARGS=!PY_ARGS! --diffusion-steps %~2"

shift

shift

goto parse_args



:arg_length_adjust

set "PY_ARGS=!PY_ARGS! --length-adjust %~2"

shift

shift

goto parse_args



:arg_inference_cfg_rate

set "PY_ARGS=!PY_ARGS! --inference-cfg-rate %~2"

shift

shift

goto parse_args



:arg_semi_tone_shift

set "PY_ARGS=!PY_ARGS! --semi-tone-shift %~2"

shift

shift

goto parse_args



:arg_limit

set "PY_ARGS=!PY_ARGS! --limit %~2"

shift

shift

goto parse_args



:run_convert

python "%ROOT%\scripts\convert-slices.py" !PY_ARGS!

exit /b %ERRORLEVEL%



:usage

echo Usage: convert-slices.bat ^<slices_dir^> [options passed to convert-slices.py]

echo Example: convert-slices.bat output\slices\test

echo          convert-slices.bat output\slices\test --limit 1

exit /b 1

