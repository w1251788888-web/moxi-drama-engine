#!/bin/bash
# 启动墨戏生花后台管理台（生产模式）
# 双击后会构建前端、启动后端，并自动打开 /moxi-admin

cd "$(dirname "$0")/../01-system-core"
source .venv/bin/activate

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

echo "更新缓存版本戳: $BUILD_TIME"
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/BUILD_VERSION_PLACEHOLDER/$BUILD_TIME/g" static/index.html
else
    sed -i "s/BUILD_VERSION_PLACEHOLDER/$BUILD_TIME/g" static/index.html
fi

PID=$(lsof -ti :6565 2>/dev/null)
if [ -n "$PID" ]; then
    echo "停止已有后端服务 (PID: $PID)"
    kill $PID 2>/dev/null
    sleep 2
fi

echo "正在启动墨戏生花后台..."
echo "后台地址: http://127.0.0.1:6565/moxi-admin"
echo "管理员账号: admin"
echo ""

python -m uvicorn app.main:app --host 0.0.0.0 --port 6565 --no-access-log &
echo $! > /tmp/moxi-admin.pid

sleep 3

if curl -sf http://127.0.0.1:6565/api/health >/dev/null 2>&1; then
    echo "✅ 后台服务启动成功，正在打开浏览器..."
    open "http://127.0.0.1:6565/moxi-admin"
else
    echo "⏳ 服务启动中，请稍候..."
    sleep 2
    open "http://127.0.0.1:6565/moxi-admin"
fi

wait

