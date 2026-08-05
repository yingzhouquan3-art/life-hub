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

# 默认只监听回环。需要手机访问时：
#   LIFE_HUB_HOST=tailscale ./run.sh      自动找本机的 Tailscale 地址
#   LIFE_HUB_HOST=100.x.x.x ./run.sh      指定地址
# 刻意不支持 0.0.0.0：那会把生活数据暴露给当前连着的任何网络。
HOST="${LIFE_HUB_HOST:-127.0.0.1}"
if [ "$HOST" = "tailscale" ]; then
  HOST="$("$VENV/bin/python" -c 'from backend.core.access import detect_tailscale_ip; print(detect_tailscale_ip() or "")')"
  if [ -z "$HOST" ]; then
    echo "[run] 没有找到 Tailscale 地址，改为只监听本机"
    HOST="127.0.0.1"
  fi
fi
if [ "$HOST" = "0.0.0.0" ]; then
  echo "[run] 拒绝监听 0.0.0.0，请填具体的 Tailscale 地址" >&2
  exit 1
fi

echo "[run] starting on http://$HOST:$PORT"
echo "[run] 手机配对页面：http://127.0.0.1:$PORT/pair.html"
( sleep 1.2 && open "http://127.0.0.1:$PORT" ) &
exec "$VENV/bin/python" -m uvicorn backend.main:app --host "$HOST" --port $PORT --reload
