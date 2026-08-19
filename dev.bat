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

:: Validate backend config
echo Validating config...
cd /d %~dp0\backend
python -c "from app.core.config import settings; print('[OK] Database:', settings.DATABASE_URL); print('[OK] CORS:', settings.CORS_ORIGINS[:2] if len(settings.CORS_ORIGINS) > 2 else settings.CORS_ORIGINS)"
cd /d %~dp0
echo.

:: Stop stale Celery workers before loading current source
echo [WORKER] Stopping stale Celery workers before loading current source...
pushd "%~dp0backend"
"%~dp0.venv\Scripts\celery.exe" -A app.celery_app.celery_app control shutdown >nul 2>&1
popd
timeout /t 2 /nobreak >nul

:: Prefer Windows Terminal: one window with five tabs; fallback to five windows
where wt >nul 2>&1
if errorlevel 1 goto legacy_start

echo [MODE] Windows Terminal detected: launching 1 window with 5 tabs...
echo.

echo [1/5] Starting FastAPI Backend Server (WebSocket Enabled)...
wt -w shiguang new-tab --title "拾光工坊 Backend" -d "%~dp0." cmd /k "call .venv\Scripts\activate.bat && cd backend && set PYTHONUNBUFFERED=1 && python -u -m uvicorn app.main:application --host 0.0.0.0 --port 8000 --reload"
echo [WAIT] Waiting for backend to start...
timeout /t 3 /nobreak >nul

echo [2/5] Starting Celery Worker (Audiobook Queue, solo pool)...
wt -w shiguang new-tab --title "拾光工坊 Celery-Audiobook" -d "%~dp0." cmd /k "call .venv\Scripts\activate.bat && cd backend && celery -A app.celery_app.celery_app worker -P solo -Q audiobook -n audiobook@%%h -l info"
echo [WAIT] Giving Celery worker a moment to attach...
timeout /t 2 /nobreak >nul

echo [3/5] Starting Celery Worker (DreamWeaver Queue, solo pool)...
wt -w shiguang new-tab --title "拾光工坊 Celery-DreamWeaver" -d "%~dp0." cmd /k "call .venv\Scripts\activate.bat && cd backend && celery -A app.celery_app.celery_app worker -P solo -Q dreamweaver -n dreamweaver@%%h -l info"
echo [WAIT] Giving Celery worker a moment to attach...
timeout /t 2 /nobreak >nul

echo [4/5] Starting Celery Beat (dispatcher/billing finalizer schedules)...
wt -w shiguang new-tab --title "拾光工坊 Celery-Beat" -d "%~dp0." cmd /k "call .venv\Scripts\activate.bat && cd backend && celery -A app.celery_app.celery_app beat -l info"
echo [WAIT] Giving Celery beat a moment to attach...
timeout /t 2 /nobreak >nul

echo [5/5] Starting Frontend Dev Server...
wt -w shiguang new-tab --title "拾光工坊 Frontend" -d "%~dp0." cmd /k "call .venv\Scripts\activate.bat && cd frontend && npm run dev"
goto started

:legacy_start
echo [MODE] Windows Terminal not found: falling back to 4 separate windows...
echo.

echo [1/5] Starting FastAPI Backend Server (WebSocket Enabled)...
start "拾光工坊 - Backend (FastAPI + WebSocket)" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd backend && set PYTHONUNBUFFERED=1 && python -u -m uvicorn app.main:application --host 0.0.0.0 --port 8000 --reload"
echo [WAIT] Waiting for backend to start...
timeout /t 3 /nobreak >nul

echo [2/5] Starting Celery Worker (Audiobook Queue, solo pool)...
start "拾光工坊 - Celery Worker (Audiobook)" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd backend && celery -A app.celery_app.celery_app worker -P solo -Q audiobook -n audiobook@%%h -l info"
echo [WAIT] Giving Celery worker a moment to attach...
timeout /t 2 /nobreak >nul

echo [3/5] Starting Celery Worker (DreamWeaver Queue, solo pool)...
start "拾光工坊 - Celery Worker (DreamWeaver)" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd backend && celery -A app.celery_app.celery_app worker -P solo -Q dreamweaver -n dreamweaver@%%h -l info"
echo [WAIT] Giving Celery worker a moment to attach...
timeout /t 2 /nobreak >nul

echo [4/5] Starting Celery Beat (dispatcher/billing finalizer schedules)...
start "拾光工坊 - Celery Beat" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd backend && celery -A app.celery_app.celery_app beat -l info"
echo [WAIT] Giving Celery beat a moment to attach...
timeout /t 2 /nobreak >nul

echo [5/5] Starting Frontend Dev Server...
start "拾光工坊 - Frontend" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && cd frontend && npm run dev"

:started
echo.
echo ================================================================
echo [SUCCESS] System Started!
echo ================================================================
echo.
echo Service URLs:
echo    - Frontend: http://localhost:5173
echo    - Backend: http://127.0.0.1:8000
echo    - API Docs: http://127.0.0.1:8000/docs
echo    - WebSocket: ws://127.0.0.1:8000/socket.io/
echo.
echo Tips:
echo    - Preferred mode: ONE Windows Terminal window with 5 tabs (Backend + Celery x2 + Beat + Frontend)
echo    - Close that one window to stop all five services at once
echo    - Precise cleanup fallback: powershell -File dev-kill.ps1
echo    - Celery workers do not auto-reload; restart them after backend code changes
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
