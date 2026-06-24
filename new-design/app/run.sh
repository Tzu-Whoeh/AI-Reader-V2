#!/usr/bin/env bash
# AI Reader (new-design) 独立应用 · 一键启动(多小说库)
# 用法: ./run.sh [端口] [base前缀]
# 前置: 已 npm run build 生成 server/static/;ollama 隧道(或设 OLLAMA_URL)。
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"   # app/ 目录(库根:其下 raw/ input/ output/)
PORT="${1:-8080}"
BASE="${2:-}"
export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:18434}"
cd "$(dirname "$HERE")"   # 到 new-design/(让 app 包可 import)
python3 -m app.server.main \
  --lib "$HERE" \
  --base-path "$BASE" \
  --port "$PORT"
