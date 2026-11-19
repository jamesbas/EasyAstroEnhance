@echo off
setlocal
title EasyAstroEnhance
pushd "%~dp0backend" || exit /b 1
"%~dp0runtime\python.exe" -E -s -B -m app.serve
set "APP_EXIT=%ERRORLEVEL%"
popd
if not "%APP_EXIT%"=="0" (
    echo.
    echo EasyAstroEnhance could not run. If it is already open, use the existing browser tab.
    pause
)
exit /b %APP_EXIT%
