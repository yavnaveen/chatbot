@echo off
setlocal
title Tunnel Excavation AI - Local Runner
cd /d "%~dp0"

echo ======================================================================
echo           Starting Tunnel Excavation AI (Clean Startup Mode)
echo ======================================================================
echo.

:: 1. Kill old processes on port 8000 and 5173 to free previous memory
echo [1/4] Freeing previous memory and stopping existing instances...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a > nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5173 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a > nul 2>&1
)
powershell -Command "Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" > nul 2>&1
echo       [OK] Previous process memory freed.

:: 2. Clear cache files (__pycache__, .pytest_cache, vite cache)
echo.
echo [2/4] Clearing cache files (__pycache__, vite build cache)...
python backend/clean.py
echo       [OK] Cache files cleaned.

:: 3. Check & start Ollama if not running
echo.
echo [3/4] Checking Ollama service...
curl -s http://127.0.0.1:11434/api/tags > nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo       Starting Ollama in background...
    start "" /B ollama serve > nul 2>&1
    timeout /t 2 /nobreak > nul
)
echo       [OK] Ollama is ready.

:: 4. Start Backend & Frontend fresh
echo.
echo [4/4] Starting fresh Backend (port 8000) and Frontend (port 5173)...
start "Chatbot-Backend" /B python server.py
timeout /t 2 /nobreak > nul
echo       [OK] Backend running on http://localhost:8000.

start "Chatbot-Frontend" /D "%~dp0frontend" /B cmd /c "npm run dev"
timeout /t 3 /nobreak > nul
echo       [OK] Frontend running on http://localhost:5173.

:: Automatically open browser
start http://localhost:5173

echo.
echo ======================================================================
echo                  CHATBOT IS RUNNING FRESH!
echo ======================================================================
echo  Chat Web UI:         http://localhost:5173
echo  Interactive Docs:    http://localhost:8000/docs
echo  Health Check:        http://localhost:8000/health
echo ======================================================================
echo.
echo Chatbot browser window opened.
echo Leave this terminal open while using the chatbot.
echo To stop the server, press Ctrl+C or close this window.
echo.

pause > nul
