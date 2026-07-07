@echo off
REM Query APISIX metrics for April 11, 2026 (12pm - 9pm)

echo Querying APISIX CPU and Memory metrics for April 11, 2026 (12:00 PM - 9:00 PM)
echo ================================================================================
echo.

REM Set variables
set NAMESPACE=cro-apisix-prod
set START_TIME=2026-03-11T10:00:00Z
set END_TIME=2026-03-11T19:00:00Z
set STEP=5m

REM Check if logged in
oc whoami >nul 2>&1
if errorlevel 1 (
    echo Error: Not logged into OpenShift. Please run: oc login
    exit /b 1
)

echo Switching to namespace: %NAMESPACE%
oc project %NAMESPACE%
echo.

REM Try to get Thanos route
echo Checking for Thanos Querier access...
oc get route thanos-querier -n openshift-monitoring -o jsonpath="{.spec.host}" >thanos_host.tmp 2>nul
if errorlevel 1 (
    echo.
    echo Thanos Querier not accessible via route.
    echo.
    echo Alternative: Use OpenShift Web Console
    echo 1. Go to: Observe -^> Metrics
    echo 2. Set time range: 2026-04-11 12:00:00 to 2026-04-11 21:00:00
    echo 3. Run these queries:
    echo.
    echo CPU Query:
    echo sum^(rate^(container_cpu_usage_seconds_total{namespace="cro-apisix-prod",pod=~"apisix-.*",container="apisix"}[5m]^)^) by ^(pod^)
    echo.
    echo Memory Query:
    echo sum^(container_memory_working_set_bytes{namespace="cro-apisix-prod",pod=~"apisix-.*",container="apisix"}^) by ^(pod^)
    echo.
    del thanos_host.tmp 2>nul
    exit /b 1
)

set /p THANOS_HOST=<thanos_host.tmp
del thanos_host.tmp

echo Thanos Host: %THANOS_HOST%
echo.

REM Get token
for /f "delims=" %%i in ('oc whoami -t') do set TOKEN=%%i

echo Querying CPU metrics...
curl -k -H "Authorization: Bearer %TOKEN%" "https://%THANOS_HOST%/api/v1/query?query=sum(rate(container_cpu_usage_seconds_total{namespace=\"%NAMESPACE%\",pod=~\"apisix-.*\",container=\"apisix\"}[5m]))by(pod)&time=%END_TIME%"
echo.
echo.

echo Querying Memory metrics...
curl -k -H "Authorization: Bearer %TOKEN%" "https://%THANOS_HOST%/api/v1/query?query=sum(container_memory_working_set_bytes{namespace=\"%NAMESPACE%\",pod=~\"apisix-.*\",container=\"apisix\"})by(pod)&time=%END_TIME%"
echo.
echo.

echo ================================================================================
echo Query completed
echo.
echo For detailed graphs, use OpenShift Console: Observe -^> Metrics
