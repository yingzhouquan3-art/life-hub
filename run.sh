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
echo "[run] starting on http://127.0.0.1:$PORT"
( sleep 1.2 && open "http://127.0.0.1:$PORT" ) &
exec "$VENV/bin/python" -m uvicorn backend.main:app --host 127.0.0.1 --port $PORT --reload
