@echo off
cd /d "%~dp0"
call npm install
echo.
echo Starting frontend on http://localhost:5173 ...
echo.
call npx vite
pause
