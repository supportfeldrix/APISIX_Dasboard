@echo off
REM =============================================================================
REM  Build and push APISIX Dashboard images to OpenShift internal registry
REM  Run this BEFORE applying openshift-deploy.yaml
REM =============================================================================

set OC_EXE=%~dp0..\oc\oc.exe
set REGISTRY=default-route-openshift-image-registry.apps.dev-02-rb.ocp.fnb.co.za
set NAMESPACE=cro-apisix-uat
set TAG=1.0.0

echo.
echo ============================================
echo   Building APISIX Dashboard Images
echo ============================================
echo.

REM --- Check podman/docker ---
podman --version >nul 2>&1
if errorlevel 1 (
    docker --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Neither podman nor docker found. Install one of them.
        pause
        exit /b 1
    )
    set BUILD_CMD=docker
) else (
    set BUILD_CMD=podman
)
echo Using: %BUILD_CMD%

REM --- Login to OpenShift ---
echo.
echo [1/6] Logging into OpenShift...
"%OC_EXE%" whoami >nul 2>&1
if errorlevel 1 (
    echo ERROR: Not logged into OpenShift. Run: oc login --token=... --server=...
    pause
    exit /b 1
)
echo   Logged in as: 
"%OC_EXE%" whoami

REM --- Login to registry ---
echo.
echo [2/6] Logging into OpenShift image registry...
"%OC_EXE%" registry login --insecure=true
if errorlevel 1 (
    echo Trying alternative registry login...
    for /f "tokens=*" %%t in ('"%OC_EXE%" whoami -t') do set OC_TOKEN=%%t
    %BUILD_CMD% login -u unused -p %OC_TOKEN% %REGISTRY% --tls-verify=false
)

REM --- Build backend ---
echo.
echo [3/6] Building backend image...
cd /d "%~dp0..\backend"
%BUILD_CMD% build -t %REGISTRY%/%NAMESPACE%/apisix-dashboard-backend:%TAG% .
if errorlevel 1 (
    echo ERROR: Backend build failed.
    pause
    exit /b 1
)
echo   Backend image built.

REM --- Build frontend ---
echo.
echo [4/6] Building frontend image...
cd /d "%~dp0..\frontend"
%BUILD_CMD% build -t %REGISTRY%/%NAMESPACE%/apisix-dashboard-frontend:%TAG% .
if errorlevel 1 (
    echo ERROR: Frontend build failed.
    pause
    exit /b 1
)
echo   Frontend image built.

REM --- Push backend ---
echo.
echo [5/6] Pushing backend image...
%BUILD_CMD% push %REGISTRY%/%NAMESPACE%/apisix-dashboard-backend:%TAG% --tls-verify=false
if errorlevel 1 (
    echo ERROR: Backend push failed. Check registry access.
    pause
    exit /b 1
)
echo   Backend pushed.

REM --- Push frontend ---
echo.
echo [6/6] Pushing frontend image...
%BUILD_CMD% push %REGISTRY%/%NAMESPACE%/apisix-dashboard-frontend:%TAG% --tls-verify=false
if errorlevel 1 (
    echo ERROR: Frontend push failed. Check registry access.
    pause
    exit /b 1
)
echo   Frontend pushed.

echo.
echo ============================================
echo   Images built and pushed successfully!
echo ============================================
echo.
echo   Backend:  %REGISTRY%/%NAMESPACE%/apisix-dashboard-backend:%TAG%
echo   Frontend: %REGISTRY%/%NAMESPACE%/apisix-dashboard-frontend:%TAG%
echo.
echo   Now run:
echo     "%OC_EXE%" apply -f "%~dp0openshift-deploy.yaml" -n %NAMESPACE%
echo.
pause
