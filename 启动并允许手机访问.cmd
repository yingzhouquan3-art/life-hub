@echo off
rem Keep this file pure ASCII: cmd.exe reads .cmd using the local ANSI
rem codepage, so UTF-8 Chinese here becomes garbage and gets run as commands.
rem auto: use Tailscale when available, otherwise the current LAN.
rem Falls back to loopback when neither is found, so nothing is exposed by accident.
set "LIFE_HUB_HOST=auto"
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0windows\start.ps1" -NoBrowser
timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:8766/pair.html"
exit /b 0
