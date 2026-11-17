@echo off
setlocal
title Tunnel Excavation AI - Local Runner
cd /d "%~dp0"

echo ======================================================================
echo           Starting Tunnel Excavation AI (Local System Mode)
echo ======================================================================
echo.

:: 1. Check & start Ollama if not running
echo [1/3] Checking Ollama service...
curl -s http://127.0.0.1:11434/api/tags > nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo       Starting Ollama in background...
    start "" /B ollama serve > nul 2>&1
    timeout /t 2 /nobreak > nul
)
echo       [OK] Ollama is ready.

:: 2. Stop old backend on port 8000 if running, and start fresh
echo.
echo [2/3] Starting Backend API Server on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a > nul 2>&1
)
timeout /t 1 /nobreak > nul
start "Chatbot-Backend" /B python server.py
timeout /t 2 /nobreak > nul
echo       [OK] Backend running on http://localhost:8000.

:: 3. Start Frontend React Web UI
echo.
echo [3/3] Starting Frontend React UI on port 5173...
netstat -ano | findstr :5173 | findstr LISTENING > nul 2>&1
if %ERRORLEVEL% neq 0 (
    start "Chatbot-Frontend" /D "%~dp0frontend" /B cmd /c "npm run dev"
    timeout /t 3 /nobreak > nul
)
echo       [OK] Frontend running on http://localhost:5173.

:: Automatically open browser
start http://localhost:5173

echo.
echo ======================================================================
echo                  CHATBOT IS RUNNING LOCALLY!
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
