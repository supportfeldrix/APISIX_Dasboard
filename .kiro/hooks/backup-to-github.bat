@echo off
REM Auto-commit working changes, push to FNB (origin), then refresh the
REM cleaned backup mirror on the private GitHub repo (oc.exe binaries stripped).
setlocal
set REPO=c:\Users\F5151422\OneDrive - FRG\Desktop\APISIX_Dashboard

REM 1. Stage and commit any changes on the working branch
git -C "%REPO%" add -A
git -C "%REPO%" diff --cached --quiet
if errorlevel 1 (
    git -C "%REPO%" commit -m "Auto-commit from Kiro hook"
)

REM 2. Push working branch to FNB origin (primary)
git -C "%REPO%" push origin HEAD

REM 3. Refresh cleaned backup on GitHub
REM    Reset the mirror branch to current work, strip oc.exe binaries, force-push.
git -C "%REPO%" branch -f github-clean APISIX_Dashboard_CROIT
set FILTER_BRANCH_SQUELCH_WARNING=1
git -C "%REPO%" filter-branch -f --index-filter "git rm -r --cached --ignore-unmatch oc/oc.exe PROD/oc/oc.exe UAT/oc/oc.exe" --prune-empty github-clean
git -C "%REPO%" push -f github github-clean:APISIX_Dashboard_CROIT

endlocal
