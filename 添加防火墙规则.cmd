@echo off
rem Keep this file pure ASCII.
rem cmd.exe reads .cmd using the local ANSI codepage (936 on this machine),
rem so any UTF-8 Chinese here turns into garbage and gets run as commands.
rem All user-facing Chinese lives in the PowerShell script, which has a BOM.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\allow-mobile-access.ps1"
exit /b 0
