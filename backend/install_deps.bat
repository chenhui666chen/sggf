@echo off
echo ================================================================
echo Installing Backend Dependencies
echo ================================================================
echo.

cd /d "%~dp0"

echo [1/3] Installing core packages...
pip install fastapi uvicorn[standard] sqlalchemy pydantic pydantic-settings python-dotenv

echo.
echo [2/3] Installing LangChain packages...
pip install langchain langchain-community langchain-core chromadb dashscope tiktoken

echo.
echo [3/3] Installing other dependencies...
pip install python-socketio python-engineio python-multipart python-jose[cryptography] passlib[bcrypt] alembic redis celery httpx pytest pytest-asyncio pytest-cov python-docx email-validator

echo.
echo ================================================================
echo [SUCCESS] All dependencies installed!
echo ================================================================
pause

