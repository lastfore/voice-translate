@echo off
REM Seed-VC Web UI shutdown script
REM See docs/Seed-VC安装指南.md section 5.1

setlocal enabledelayedexpansion
set FOUND=0

for /f "tokens=5" %%a in ('netstat -ano ^| findstr "127.0.0.1:7860" ^| findstr "LISTENING"') do (
  echo Stopping Seed-VC Web UI, PID %%a ...
  taskkill /PID %%a /T /F >nul 2>&1
  if errorlevel 1 (
    echo Failed to stop PID %%a
  ) else (
    echo Stopped.
    set FOUND=1
  )
)

if !FOUND!==0 (
  echo No process listening on 127.0.0.1:7860.
)

endlocal
