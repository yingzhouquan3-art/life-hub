@echo off
chcp 65001 >nul
title 我的生活中枢 · 放行手机访问

echo.
echo   这一步会修改 Windows 防火墙设置，需要管理员权限。
echo   接下来会弹出系统提示，请点「是」。
echo.
echo   脚本只会：
echo     1. 加一条放行 8766 端口的入站规则（仅专用网络）
echo     2. 如果当前网络是「公用」，询问你是否改成「专用」
echo.
echo   不会关闭防火墙，也不会改动其他规则。
echo.
pause

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0windows\allow-mobile-access.ps1'"

exit /b 0
