@echo off
REM Re-download and verify the MelBand-RoFormer model if corrupted
REM See docs/词曲分离与声乐切片安装指南.md section 8.6

setlocal

set ROOT=D:\code\voice-translate
set MODEL_DIR=%ROOT%\separator-env\models\audio-separator
set MODEL_FILE=%MODEL_DIR%\mel_band_roformer_kim_ft_unwa.ckpt
set MODEL_URL=https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/mel_band_roformer_kim_ft_unwa.ckpt
set EXPECTED_SIZE=913100690

if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"

echo Checking model: %MODEL_FILE%

call %ROOT%\separator-env\Scripts\activate.bat
python "%ROOT%\scripts\verify-separator-model.py"
if %errorlevel%==0 (
    echo Model is valid. No repair needed.
    exit /b 0
)

echo Model missing or corrupted. Re-downloading...
if exist "%MODEL_FILE%" del /f "%MODEL_FILE%"

curl -L --retry 5 --retry-delay 3 -o "%MODEL_FILE%" "%MODEL_URL%"
if errorlevel 1 (
    echo curl download failed.
    exit /b 1
)

for %%A in ("%MODEL_FILE%") do set SIZE=%%~zA
if not "%SIZE%"=="%EXPECTED_SIZE%" (
    echo Unexpected file size: %SIZE% ^(expected %EXPECTED_SIZE%^)
    exit /b 1
)

python "%ROOT%\scripts\verify-separator-model.py"
if errorlevel 1 (
    echo Verification failed after download.
    exit /b 1
)

echo Model repaired successfully.
endlocal
