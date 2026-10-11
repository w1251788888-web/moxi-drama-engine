#!/bin/bash
# 开发模式 — 前后端分离热重载
#
# 后端: http://127.0.0.1:6565  (--reload，改 Python 代码自动重启)
# 前端: http://localhost:5173   (Vite HMR，改 Vue/TS 代码即时生效)
#
# API 调用走 Vite 代理：浏览器 → 5173/api/* → 6565/api/*
# 登录 token 持久化到 SQLite，后端重启后无需重新登录

cd "$(dirname "$0")/../01-system-core"
source .venv/bin/activate

# 清理旧进程
for port in 6565 5173; do
    PID=$(lsof -ti :$port 2>/dev/null)
    if [ -n "$PID" ]; then
        echo "停止端口 $port 上的旧进程 (PID: $PID)"
        kill $PID 2>/dev/null
        sleep 1
    fi
done

echo "启动后端服务（--reload 模式）..."
python -m uvicorn app.main:app --host 0.0.0.0 --port 6565 --reload &
BACKEND_PID=$!

sleep 2

cd webui
echo "启动前端开发服务器（Vite HMR）..."
npm run dev &
FRONTEND_PID=$!

echo ""
echo "──────────────────────────────────────"
echo "  后端 API:   http://127.0.0.1:6565"
echo "  前端开发:   http://localhost:5173  ← 推荐使用这个"
echo "──────────────────────────────────────"
echo "Ctrl+C 停止所有服务"
echo ""

# Ctrl+C 时同时停止前后端
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

wait
