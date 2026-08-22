@echo off
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\setup-reminder.ps1"
exit /b 0
