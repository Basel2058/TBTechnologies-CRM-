@echo off
chcp 65001 >nul
cd /d "%~dp0"
title TBT CRM

where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Preparing for the first time, please wait...
  py -3 -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
".venv\Scripts\python.exe" run.py
pause
