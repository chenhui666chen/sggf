@echo off
chcp 65001 >nul
cd /d "%~dp0"
cls

echo ================================================================
echo Start Novel Writing System - FastAPI + WebSocket
echo ================================================================
echo.
echo WebSocket Support: YES
echo Real-time Communication: YES
echo.
echo ================================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH
    pause
    exit /b 1
)

:: Check Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found in PATH
    pause
    exit /b 1
)

echo [OK] Python Ready
echo [OK] Node.js Ready
echo.

:: Activate Virtual Environment
echo [INIT] Activating virtual environment...
if exist ".venv\Scripts\Activate.ps1" (
    powershell -Command "& '.venv\Scripts\Activate.ps1'"
    echo [OK] Virtual environment activated
) else (
    echo [WARNING] Virtual environment not found, using global Python
)
echo.

:: Start Backend
echo [1/3] Starting FastAPI Backend Server (WebSocket Enabled)...
echo.
echo Validating config...
cd /d %~dp0\backend
python -c "from app.core.config import settings; print('[OK] Database:', settings.DATABASE_URL); print('[OK] CORS:', settings.CORS_ORIGINS[:2] if len(settings.CORS_ORIGINS) > 2 else settings.CORS_ORIGINS)"
cd /d %~dp0
echo.
start "Novel System - Backend (FastAPI + WebSocket)" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd backend && set PYTHONUNBUFFERED=1 && python -u -m uvicorn app.main:application --host 0.0.0.0 --port 8000 --reload"

:: Wait for backend
echo [WAIT] Waiting for backend to start...
timeout /t 3 /nobreak >nul

:: Start Celery Worker for Audiobook Tasks
echo [2/3] Starting Celery Worker (Audiobook Queue, solo pool)...
start "Novel System - Celery Worker" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd backend && celery -A app.celery_app.celery_app worker -P solo -Q audiobook -l info"
echo [WAIT] Giving Celery worker a moment to attach...
timeout /t 2 /nobreak >nul

:: Start Frontend
echo [3/3] Starting Frontend Dev Server...
start "Novel System - Frontend" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd frontend && npm run dev"

echo.
echo ================================================================
echo [SUCCESS] System Started!
echo ================================================================
echo.
echo Service URLs:
echo    - Frontend: http://localhost:5173
echo    - Backend: http://localhost:8000
echo    - API Docs: http://localhost:8000/docs
echo    - WebSocket: ws://localhost:8000/socket.io/
echo.
echo Tips:
echo    - Two new windows opened (Backend + Frontend)
echo    - Close window to stop service
echo    - Press any key to open browser...
echo.
echo ================================================================

pause

:: Open browser
start http://localhost:5173

echo.
echo [DONE] Browser opened, enjoy!
echo.
pause
