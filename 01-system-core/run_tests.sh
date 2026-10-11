#!/bin/bash
# 运行单元测试

cd "$(dirname "$0")"

# 激活虚拟环境
source .venv/bin/activate

# 运行测试
echo "运行 LightweightLearningService 单元测试..."
pytest tests/services/test_lightweight_learning_service.py -v

echo ""
echo "运行所有测试..."
pytest tests/ -v
