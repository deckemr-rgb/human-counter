@echo off
title Human Counter v2
cd /d "%~dp0"
if not exist .venv (
  echo [setup] membuat venv + dependensi...
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
echo [jalankan] Human Counter v2 → http://localhost:5103
.venv\Scripts\python.exe server_main.py
