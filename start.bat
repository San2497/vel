@echo off
setlocal
cd /d "%~dp0"

if not exist "centrala\.venv\Scripts\python.exe" (
    echo [1/4] Creating virtual environment for centrala...
    python -m venv "centrala\.venv"
    "centrala\.venv\Scripts\python.exe" -m pip install -r "centrala\requirements.txt"
)

if not exist "terminal\.venv\Scripts\python.exe" (
    echo [2/4] Creating virtual environment for terminal...
    python -m venv "terminal\.venv"
    "terminal\.venv\Scripts\python.exe" -m pip install -r "terminal\requirements.txt"
)

if not exist "centrala\.env" (
    echo [3/4] Creating centrala\.env from .env.example...
    copy "centrala\.env.example" "centrala\.env" >nul
)

if not exist "terminal\.env" (
    echo [4/4] Creating terminal\.env from .env.example...
    copy "terminal\.env.example" "terminal\.env" >nul
)

echo Starting Centrala (port 8080) and Terminal (port 8081)...
start "Centrala (8080)" cmd /k "cd /d ""%~dp0centrala"" && .venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8080"
timeout /t 2 /nobreak >nul
start "Terminal (8081)" cmd /k "cd /d ""%~dp0terminal"" && .venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8081"
timeout /t 2 /nobreak >nul

start "" "http://127.0.0.1:8081/"
start "" "http://127.0.0.1:8080/qr"
