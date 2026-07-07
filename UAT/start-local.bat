@echo off
echo Starting APISIX Dashboard (local development)...
echo.
echo Starting backend...
start "APISIX Backend" cmd /k "cd /d %~dp0backend && python run.py"
timeout /t 3 /nobreak > nul
echo Starting frontend...
start "APISIX Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
echo.
echo Dashboard will be available at http://localhost:5173
echo Backend API at http://localhost:8000
echo API docs at http://localhost:8000/docs
