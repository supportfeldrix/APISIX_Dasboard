@echo off
REM ============================================================================
REM  APISIX Dashboard - Full Local Startup Script
REM  Logs into OpenShift, port-forwards APISIX Admin API, starts backend+frontend.
REM ============================================================================

echo.
echo ============================================
echo   APISIX Dashboard - Local Development
echo ============================================
echo.

REM --- Configuration ---
set OC_TOKEN=sha256~KYsPIZSJsEuzXKQHFTxwIAD1dKGZsW0mZbjC44xdcBc
set OC_SERVER=https://api.dev-02-rb.ocp.fnb.co.za:6443
set OC_NAMESPACE=cro-apisix-uat
set OC_SERVICE=pod/apisix-uat-0
set OC_ADMIN_PORT=9180

REM Use local oc.exe from the oc folder
set OC_EXE=%~dp0oc\oc.exe

set JWT_SECRET=local-dev-secret-key-change-in-production
set APISIX_ADMIN_BASE_URL=http://localhost:9180
set APISIX_ADMIN_KEY=TyqjNqbWXKbmHOVGYtPfptUOXDWIGyAA
set APISIX_METRICS_URL=http://localhost:9091/apisix/prometheus/metrics
set APISIX_ADMIN_VERIFY_SSL=false
set APISIX_ADMIN_TIMEOUT=10
set APISIX_METRICS_TIMEOUT=10
set DATABASE_URL=sqlite:///./apisix_dashboard.db
set CORS_ORIGINS=http://localhost:5173
set ROOT_PATH=
set LOG_LEVEL=INFO
set JWT_ALGORITHM=HS256
set JWT_EXPIRY_MINUTES=30

REM --- Check Prerequisites ---
echo [1/8] Checking prerequisites...

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    pause
    exit /b 1
)
echo   Python:  OK

node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is not installed or not in PATH.
    pause
    exit /b 1
)
echo   Node.js: OK

if not exist "%OC_EXE%" (
    echo ERROR: oc.exe not found at %OC_EXE%
    echo Please copy the oc folder into the UAT directory.
    pause
    exit /b 1
)
echo   oc CLI:  OK (%OC_EXE%)

REM --- OpenShift Login ---
echo.
echo [2/8] Logging into OpenShift cluster...
"%OC_EXE%" login --token=%OC_TOKEN% --server=%OC_SERVER% --insecure-skip-tls-verify=true
if errorlevel 1 (
    echo ERROR: Failed to log into OpenShift. Token may have expired.
    echo Get a new token from the OpenShift web console:
    echo   https://oauth-openshift.apps.dev-02-rb.ocp.fnb.co.za/oauth/token/request
    pause
    exit /b 1
)
echo   Logged in successfully.

REM --- Switch to namespace ---
"%OC_EXE%" project %OC_NAMESPACE%
echo   Project: %OC_NAMESPACE%

REM --- Start Port-Forward ---
echo.
echo [3/8] Starting port-forward to APISIX Admin API (localhost:%OC_ADMIN_PORT%)...
start "APISIX - Port Forward (Admin)" cmd /k ""%OC_EXE%" port-forward %OC_SERVICE% %OC_ADMIN_PORT%:%OC_ADMIN_PORT% -n %OC_NAMESPACE%"
timeout /t 3 /nobreak >nul

echo   Starting port-forward to APISIX Metrics (localhost:9091)...
start "APISIX - Port Forward (Metrics)" cmd /k ""%OC_EXE%" port-forward svc/apisix-metrics 9091:9091 -n %OC_NAMESPACE%"
timeout /t 3 /nobreak >nul
echo   Port-forwards started.

REM --- Backend Setup ---
echo.
echo [4/8] Setting up backend virtual environment...
cd /d "%~dp0backend"

if not exist "venv" (
    echo   Creating Python virtual environment...
    python -m venv venv
)

REM --- Write .env file ---
echo   Writing .env file...
(
    echo JWT_SECRET=%JWT_SECRET%
    echo JWT_ALGORITHM=%JWT_ALGORITHM%
    echo JWT_EXPIRY_MINUTES=%JWT_EXPIRY_MINUTES%
    echo APISIX_ADMIN_BASE_URL=%APISIX_ADMIN_BASE_URL%
    echo APISIX_ADMIN_KEY=%APISIX_ADMIN_KEY%
    echo APISIX_ADMIN_VERIFY_SSL=%APISIX_ADMIN_VERIFY_SSL%
    echo APISIX_ADMIN_TIMEOUT=%APISIX_ADMIN_TIMEOUT%
    echo APISIX_METRICS_URL=%APISIX_METRICS_URL%
    echo APISIX_METRICS_TIMEOUT=%APISIX_METRICS_TIMEOUT%
    echo DATABASE_URL=%DATABASE_URL%
    echo CORS_ORIGINS=%CORS_ORIGINS%
    echo ROOT_PATH=%ROOT_PATH%
    echo LOG_LEVEL=%LOG_LEVEL%
    echo OC_API_SERVER=%OC_SERVER%
    echo OC_TOKEN=%OC_TOKEN%
    echo OC_NAMESPACE=%OC_NAMESPACE%
    echo OC_VERIFY_SSL=false
    echo LDAP_ENABLED=true
    echo LDAP_SERVER=ldaps://ldap.fnbconnect.co.za:636
    echo LDAP_BASE_DN=DC=fnb,DC=co,DC=za
    echo LDAP_USER_FILTER=^(^&^(objectClass=user^)^(sAMAccountName={username}^)^)
    echo LDAP_BIND_DN=SVC_cro_ansible_dev@fnb.co.za
    echo LDAP_BIND_PASSWORD=InwxvJ.NWkaYf*1s
    echo LDAP_GROUP_BASE_DN=OU=GlobalSecurityGroups,OU=DomainGroups,DC=fnb,DC=co,DC=za
    echo LDAP_ADMIN_GROUP=
    echo LDAP_USE_SSL=true
    echo LDAP_VERIFY_SSL=false
) > .env
echo   .env written.

REM --- Start Backend ---
echo.
echo [5/8] Starting backend server (port 8000)...
start "APISIX - Backend" "%~dp0backend\run_backend.bat"
timeout /t 5 /nobreak >nul

REM --- Start Frontend ---
echo.
echo [6/8] Starting frontend dev server (port 5173)...
start "APISIX - Frontend" "%~dp0frontend\run_frontend.bat"
timeout /t 8 /nobreak >nul

REM --- Open Browser ---
echo.
echo [7/8] Opening browser...
start http://localhost:5173

echo.
echo ============================================
echo   All services started!
echo ============================================
echo.
echo   Backend API:    http://localhost:8000
echo   API Docs:       http://localhost:8000/docs
echo   Frontend:       http://localhost:5173
echo   APISIX Admin:   http://localhost:9180 (port-forwarded)
echo.
echo   Login:          admin / N03ntry#
echo.
echo   Terminal windows opened:
echo     - "APISIX - Port Forward (Admin)"   (oc port-forward :9180)
echo     - "APISIX - Port Forward (Metrics)" (oc port-forward :9091)
echo     - "APISIX - Backend"                (uvicorn on :8000)
echo     - "APISIX - Frontend"               (vite on :5173)
echo.
echo   Close those windows to stop everything.
echo ============================================
echo.
pause
