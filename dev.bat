@echo off
chcp 65001 >nul
cd /d "%~dp0"
cls

echo ================================================================
echo Start 拾光工坊 - FastAPI + WebSocket
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
echo [1/4] Starting FastAPI Backend Server (WebSocket Enabled)...
echo.
echo Validating config...
cd /d %~dp0\backend
python -c "from app.core.config import settings; print('[OK] Database:', settings.DATABASE_URL); print('[OK] CORS:', settings.CORS_ORIGINS[:2] if len(settings.CORS_ORIGINS) > 2 else settings.CORS_ORIGINS)"
cd /d %~dp0
echo.
start "拾光工坊 - Backend (FastAPI + WebSocket)" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd backend && set PYTHONUNBUFFERED=1 && python -u -m uvicorn app.main:application --host 0.0.0.0 --port 8000 --reload"

:: Wait for backend
echo [WAIT] Waiting for backend to start...
timeout /t 3 /nobreak >nul

:: Start Celery Workers
echo [2/4] Starting Celery Worker (Audiobook Queue, solo pool)...
start "拾光工坊 - Celery Worker (Audiobook)" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd backend && celery -A app.celery_app.celery_app worker -P solo -Q audiobook -l info"
echo [WAIT] Giving Celery worker a moment to attach...
timeout /t 2 /nobreak >nul

echo [3/4] Starting Celery Worker (DreamWeaver Queue, solo pool)...
start "拾光工坊 - Celery Worker (DreamWeaver)" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd backend && celery -A app.celery_app.celery_app worker -P solo -Q dreamweaver -l info"
echo [WAIT] Giving Celery worker a moment to attach...
timeout /t 2 /nobreak >nul

:: Start Frontend
echo [4/4] Starting Frontend Dev Server...
start "拾光工坊 - Frontend" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd frontend && npm run dev"

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
echo    - Four new windows opened (Backend + Celery Audiobook + Celery DreamWeaver + Frontend)
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
