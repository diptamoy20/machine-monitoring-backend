@echo off
title Multi-Camera YOLO Detection & Utilization Tracker
echo ========================================================
echo Starting Multi-Camera YOLO Detection & Utilization Tracker
echo Press 'q' inside any camera window to quit.
echo ========================================================
python "%~dp0detection.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Script ended with an error code: %ERRORLEVEL%
    pause
)
