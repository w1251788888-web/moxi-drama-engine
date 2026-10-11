#!/bin/bash
# 启动墨戏生花（生产模式）
# 会自动构建前端静态文件，然后通过后端统一提供服务

cd "$(dirname "$0")/../01-system-core"
source .venv/bin/activate

# ── 清理旧构建并重新构建前端 ────────────────────────────────────
echo "清理旧构建..."
rm -rf static/assets/*

echo "构建前端..."
cd webui
BUILD_TIME=$(date +%Y%m%d-%H%M%S)
npm run build-only 2>&1
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "❌ 前端构建失败，请检查上方错误信息"
    exit 1
fi
cd ..
echo ""

# ── 更新版本戳，强制浏览器刷新缓存 ───────────────────────────────
echo "更新缓存版本戳: $BUILD_TIME"
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/BUILD_VERSION_PLACEHOLDER/$BUILD_TIME/g" static/index.html
else
    sed -i "s/BUILD_VERSION_PLACEHOLDER/$BUILD_TIME/g" static/index.html
fi

# ── 停止已有服务 ──────────────────────────────────────────────────
PID=$(lsof -ti :6565 2>/dev/null)
if [ -n "$PID" ]; then
    echo "停止已有服务 (PID: $PID)"
    kill $PID 2>/dev/null
    sleep 2
fi

echo "正在启动墨戏生花..."
echo "服务地址: http://127.0.0.1:6565"
echo ""

# 启动服务
python -m uvicorn app.main:app --host 0.0.0.0 --port 6565 --no-access-log &
echo $! > /tmp/moxi.pid

# 等待服务启动
sleep 3

# 健康检查
if curl -sf http://127.0.0.1:6565/api/health >/dev/null 2>&1; then
    echo "✅ 服务启动成功，正在打开浏览器..."
    open "http://127.0.0.1:6565"
else
    echo "⏳ 服务启动中，请稍候..."
    sleep 2
    open "http://127.0.0.1:6565"
fi

# 保持脚本运行（Ctrl+C 停止）
wait
