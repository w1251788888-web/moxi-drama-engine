#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export OPENSPACE_HOST_SKILL_DIRS="${OPENSPACE_HOST_SKILL_DIRS:-$PROJECT_ROOT/05-skill-plugins/integrated-skills}"
export OPENSPACE_WORKSPACE="${OPENSPACE_WORKSPACE:-$PROJECT_ROOT/05-skill-plugins/third_party/OpenSpace}"

if ! command -v openspace-mcp >/dev/null 2>&1; then
  echo "未找到 openspace-mcp。"
  echo "请先安装 OpenSpace："
  echo "  cd \"$PROJECT_ROOT/05-skill-plugins/third_party/OpenSpace\""
  echo "  pip install -e ."
  exit 1
fi

echo "OpenSpace MCP 启动中..."
echo "OPENSPACE_HOST_SKILL_DIRS=$OPENSPACE_HOST_SKILL_DIRS"
echo "OPENSPACE_WORKSPACE=$OPENSPACE_WORKSPACE"
echo "服务地址: http://127.0.0.1:8081/mcp"

exec openspace-mcp --transport streamable-http --host 127.0.0.1 --port 8081
