#!/bin/bash
# 停止墨戏生花服务

echo "正在停止服务..."
kill $(lsof -ti :6565) 2>/dev/null
kill $(lsof -ti :5173) 2>/dev/null
echo "服务已停止"
sleep 1
