@echo off
chcp 65001 >nul
title 我的生活中枢 · 手机访问模式

rem auto：有 Tailscale 就用 Tailscale（出门在外也能连），
rem 没有就用当前局域网（手机和电脑连同一个 WiFi）。
rem 两个都找不到时自动退回「只监听本机」，不会把服务暴露出去。
set "LIFE_HUB_HOST=auto"

echo.
echo   正在启动「我的生活中枢」（手机访问模式）
echo.
echo   稍后会自动打开配对页面，把上面那条带 token 的地址发到手机上打开即可。
echo   手机和电脑要连同一个 WiFi；装了 Tailscale 的话则不受 WiFi 限制。
echo.

start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0windows\start.ps1" -NoBrowser

rem 等后端起来再打开配对页
timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:8766/pair.html"

exit /b 0
