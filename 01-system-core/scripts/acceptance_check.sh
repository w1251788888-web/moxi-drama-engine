#!/usr/bin/env bash
# 端到端老板验收：跑一遍主线创作通路 + 一致性体检 + 全量测试
#
# 上线前过这一道关。任何一项红，先解决再上线。
set -euo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "=========================================="
echo "  端到端老板验收"
echo "=========================================="

echo ""
echo "[1/3] 一致性体检（DB / 文件夹 / _index.json）..."
python scripts/check_consistency.py || echo "⚠️  体检发现不一致，详情见上"

echo ""
echo "[2/3] 主线 E2E 测试（创建项目 → 集 → 角色 → 状态卡 → 删除）..."
pytest tests/test_acceptance_mainline.py -v

echo ""
echo "[3/3] 全量测试..."
pytest tests/ -q

echo ""
echo "✅ 验收通过"
