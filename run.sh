#!/usr/bin/env bash
# 财富自由指南灯 · 一键启动
set -e
cd "$(dirname "$0")"

VENV=".venv"
if [ ! -d "$VENV" ]; then
  echo "[setup] creating venv..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r backend/requirements.txt
fi

PORT=8766

# 监听地址由 backend/serve.py 决定：回环永远监听，
# 需要手机访问时再额外加一个局域网或 Tailscale 地址。
# LIFE_HUB_HOST 可以是 auto / lan / tailscale / 具体地址，不设则只监听本机。
HOST_PREFERENCE="${LIFE_HUB_HOST:-local}"

echo "[run] 手机配对页面：http://127.0.0.1:$PORT/pair.html"
( sleep 1.2 && open "http://127.0.0.1:$PORT" ) &
exec "$VENV/bin/python" -m backend.serve --port "$PORT" --host-preference "$HOST_PREFERENCE"
