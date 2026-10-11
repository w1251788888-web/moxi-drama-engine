#!/bin/bash
# 墨戏生花 RAG · 一键启停
# 双击一次：已停则启动 + 打开浏览器；已跑则停止（保留 colima 下次秒启）
set -e
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RAG_DOCKER_DIR="$PROJECT_ROOT/02-creation-rules/dify-rag-runtime/dify/docker"

cd "$PROJECT_ROOT"

RUNNING=$(docker ps --filter "name=docker-" --format "{{.Names}}" 2>/dev/null | wc -l | tr -d ' ')

# ═══════════════════════════════════════════════
# 已运行 → 停止（仅 stop 容器，colima 保留以便秒启）
# ═══════════════════════════════════════════════
if [ "$RUNNING" -ge 10 ]; then
  clear
  echo "════════════════════════════════════════════"
  echo "  检测到 RAG 正在运行 → 执行停止"
  echo "════════════════════════════════════════════"
  cd "$RAG_DOCKER_DIR" 2>/dev/null || { echo "✗ 未找到 Dify docker 目录：$RAG_DOCKER_DIR"; exit 1; }
  echo "▶ 停止 Dify 容器..."
  docker-compose stop
  echo ""
  echo "✅ RAG 已停止（colima 保留，下次双击秒启）"
  echo ""
  echo "   如需完全释放内存 → 手动: colima stop"
  echo ""
  sleep 2
  exit 0
fi

# ═══════════════════════════════════════════════
# 未运行 → 启动
# ═══════════════════════════════════════════════
clear
echo "════════════════════════════════════════════"
echo "  启动墨戏生花 RAG"
echo "════════════════════════════════════════════"
START_TS=$(date +%s)

# 1) colima
if colima status >/dev/null 2>&1; then
  echo "✓ colima 已在运行"
else
  echo "▶ 启动 colima 虚拟机（约 60 秒）..."
  colima start --cpu 4 --memory 8 --disk 60
fi

# 2) Ollama
if pgrep -f "ollama serve" >/dev/null 2>&1; then
  echo "✓ Ollama 已在运行"
else
  echo "▶ 启动 Ollama..."
  brew services start ollama >/dev/null 2>&1 || true
fi

# 3) Dify 容器
cd "$RAG_DOCKER_DIR" 2>/dev/null || { echo "✗ 未找到 Dify docker 目录：$RAG_DOCKER_DIR"; exit 1; }
echo "▶ 启动 Dify 容器..."
docker-compose up -d

# 4) DailyHot（热榜采集源，可选）
if ! docker ps --format '{{.Names}}' | grep -q '^dailyhot$'; then
  docker start dailyhot >/dev/null 2>&1 || \
    docker run -d --name dailyhot --restart unless-stopped -p 6688:6688 jsntwdj/dailyhot:latest >/dev/null 2>&1 || true
fi

# 5) 等真实健康
echo "▶ 等待 Dify API 就绪..."
NGINX_KICKED=0
for i in {1..90}; do
  HEALTH=$(docker inspect --format='{{.State.Health.Status}}' docker-api-1 2>/dev/null || echo "starting")
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 2 http://localhost/console/api/setup 2>/dev/null || echo "000")
  if [ "$HEALTH" = "healthy" ] && { [ "$CODE" = "200" ] || [ "$CODE" = "401" ]; }; then
    echo "✅ Dify 已就绪（${i}×2s）"
    break
  fi
  if [ "$HEALTH" = "healthy" ] && [ "$CODE" = "502" ] && [ "$NGINX_KICKED" -eq 0 ]; then
    echo "  ⚠ nginx 上游 IP 失效，重启 nginx..."
    docker restart docker-nginx-1 >/dev/null 2>&1 || true
    NGINX_KICKED=1
    sleep 3
    continue
  fi
  [ $((i % 5)) -eq 0 ] && echo "  ...等待中 api=$HEALTH http=$CODE"
  sleep 2
done

ELAPSED=$(($(date +%s) - START_TS))
echo ""
echo "▶ 打开浏览器（总耗时 ${ELAPSED}s）"
CHROME_PROFILE="$HOME/Library/Application Support/MoxiRAG-Chrome"
mkdir -p "$CHROME_PROFILE"
open -na 'Google Chrome' --args \
  --user-data-dir="$CHROME_PROFILE" \
  --app=http://localhost \
  --no-first-run --no-default-browser-check 2>/dev/null \
  || open http://localhost

echo ""
echo "════════════════════════════════════════════"
echo "  RAG 已启动：http://localhost"
echo "  再次双击本文件 → 停止"
echo "════════════════════════════════════════════"
sleep 2
