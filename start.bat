@echo off
echo Cleaning up stale processes...
taskkill /F /IM pythonw.exe /T >nul 2>&1
echo Starting TS Sidekick Server...
cd server
pip install fastapi uvicorn websockets google-generativeai python-dotenv >nul 2>&1
start "" python main.py
exit
