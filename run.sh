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

# 监听地址由 backend/core/access.py 的 resolve_bind_host 统一决定。
# LIFE_HUB_HOST 可以是 auto / lan / tailscale / 具体地址，不设则只监听本机。
# 找不到目标网络会退回回环；0.0.0.0 会被明确拒绝。
BINDING="$("$VENV/bin/python" -c '
import json, os, sys
from backend.core.access import resolve_bind_host
try:
    print(json.dumps(resolve_bind_host(os.environ.get("LIFE_HUB_HOST", ""))))
except ValueError as exc:
    print(json.dumps({"error": str(exc)}))
')"
if echo "$BINDING" | grep -q '"error"'; then
  echo "[run] $BINDING" >&2
  exit 1
fi
HOST="$(echo "$BINDING" | "$VENV/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["host"])')"
echo "[run] $(echo "$BINDING" | "$VENV/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["reason"])')"

echo "[run] starting on http://$HOST:$PORT"
echo "[run] 手机配对页面：http://127.0.0.1:$PORT/pair.html"
( sleep 1.2 && open "http://127.0.0.1:$PORT" ) &
exec "$VENV/bin/python" -m uvicorn backend.main:app --host "$HOST" --port $PORT --reload
