@echo off
title Factory Analytics - Live Multi-Camera Pipeline
echo ======================================================================
echo Starting Factory Analytics Live Pipeline (main_live.py)
echo Integrated with 100%% detection.py displacement tracking ^& overlays
echo Press Ctrl+C in this window to stop cleanly.
echo ======================================================================

cd /d "%~dp0"
python factory_analytics\main_live.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Pipeline stopped with exit code: %ERRORLEVEL%
    pause
)
