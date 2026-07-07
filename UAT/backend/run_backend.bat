@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
echo.
echo Starting backend on http://localhost:8000 ...
echo.
uvicorn app.main:app --reload --port 8000
pause
