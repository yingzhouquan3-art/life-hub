@echo off
chcp 65001 >nul
title 我的生活中枢 · 手机访问模式

rem 让后端除了本机之外，还监听这台电脑的 Tailscale 地址。
rem 找不到 Tailscale 时会自动退回「只监听本机」，不会把服务暴露出去。
set "LIFE_HUB_HOST=tailscale"

echo.
echo   正在启动「我的生活中枢」（手机访问模式）
echo.
echo   稍后会自动打开配对页面，把上面那条带 token 的地址发到手机上打开即可。
echo   如果页面提示没有检测到 Tailscale，说明这台电脑还没加入你的 Tailscale 网络。
echo.

start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0windows\start.ps1" -NoBrowser

rem 等后端起来再打开配对页
timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:8766/pair.html"

exit /b 0
