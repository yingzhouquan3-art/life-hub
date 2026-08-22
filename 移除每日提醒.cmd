@echo off
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\remove-reminder.ps1"
exit /b 0
