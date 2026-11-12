@echo off
rem Launches EasyAstroEnhance (http://127.0.0.1:8765). Works from the repo folder or when copied to the Desktop.
set "APP_DIR=%~dp0"
if not exist "%APP_DIR%scripts\start.ps1" set "APP_DIR=C:\Code\EasyAstroEnhance\"
if not exist "%APP_DIR%scripts\start.ps1" (
    echo Could not find scripts\start.ps1. Edit APP_DIR in this file to point at the EasyAstroEnhance folder.
    pause
    exit /b 1
)
title EasyAstroEnhance
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%scripts\start.ps1"
if errorlevel 1 pause
