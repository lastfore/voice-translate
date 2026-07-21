@echo off
REM Seed-VC Web UI startup script
REM See docs/Seed-VC安装指南.md section 7.2 for troubleshooting

set HF_ENDPOINT=
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost

cd /d D:\code\voice-translate\seed-vc
call D:\code\voice-translate\seed-vc-env\Scripts\activate.bat

echo Starting Seed-VC Web UI at http://127.0.0.1:7860/
python app_svc.py --fp16 True
