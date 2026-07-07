@echo off
REM =============================================================================
REM  Build APISIX Dashboard images directly on OpenShift (no local Docker needed)
REM  Uses "oc new-build" with binary source upload
REM =============================================================================

set OC_EXE=%~dp0..\oc\oc.exe
set NAMESPACE=cro-apisix-uat

echo.
echo ============================================
echo   Building Images on OpenShift
echo   (No local Docker/Podman required)
echo ============================================
echo.

REM --- Check OC login ---
"%OC_EXE%" whoami >nul 2>&1
if errorlevel 1 (
    echo ERROR: Not logged into OpenShift.
    echo Run: oc login --token=... --server=https://api.dev-02-rb.ocp.fnb.co.za:6443
    pause
    exit /b 1
)
echo Logged in as:
"%OC_EXE%" whoami
"%OC_EXE%" project %NAMESPACE%

REM --- Create ImageStreams ---
echo.
echo [1/4] Creating ImageStreams...
"%OC_EXE%" create imagestream apisix-dashboard-backend -n %NAMESPACE% 2>nul
"%OC_EXE%" create imagestream apisix-dashboard-frontend -n %NAMESPACE% 2>nul
echo   ImageStreams ready.

REM --- Create BuildConfigs (if not exist) ---
echo.
echo [2/4] Creating BuildConfigs...
"%OC_EXE%" new-build --name=apisix-dashboard-backend --binary --strategy=docker --to=apisix-dashboard-backend:1.0.0 -n %NAMESPACE% 2>nul
"%OC_EXE%" new-build --name=apisix-dashboard-frontend --binary --strategy=docker --to=apisix-dashboard-frontend:1.0.0 -n %NAMESPACE% 2>nul
echo   BuildConfigs ready.

REM --- Build backend ---
echo.
echo [3/4] Building backend (uploading source to OpenShift)...
echo   This may take 2-3 minutes...
cd /d "%~dp0..\backend"
"%OC_EXE%" start-build apisix-dashboard-backend --from-dir=. --follow -n %NAMESPACE%
if errorlevel 1 (
    echo ERROR: Backend build failed. Check the build logs above.
    pause
    exit /b 1
)
echo   Backend image built successfully.

REM --- Build frontend ---
echo.
echo [4/4] Building frontend (uploading source to OpenShift)...
echo   This may take 3-5 minutes...
cd /d "%~dp0..\frontend"
"%OC_EXE%" start-build apisix-dashboard-frontend --from-dir=. --follow -n %NAMESPACE%
if errorlevel 1 (
    echo ERROR: Frontend build failed. Check the build logs above.
    pause
    exit /b 1
)
echo   Frontend image built successfully.

echo.
echo ============================================
echo   Both images built on OpenShift!
echo ============================================
echo.
echo   Backend:  image-registry.openshift-image-registry.svc:5000/%NAMESPACE%/apisix-dashboard-backend:1.0.0
echo   Frontend: image-registry.openshift-image-registry.svc:5000/%NAMESPACE%/apisix-dashboard-frontend:1.0.0
echo.
echo   Now apply the deployment:
echo     "%OC_EXE%" apply -f "%~dp0openshift-deploy.yaml" -n %NAMESPACE%
echo.
pause
