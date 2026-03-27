#!/bin/bash
# CellxGene元数据完整收集脚本
# =============================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

LOG_FILE="logs/collection_$(date +%Y%m%d_%H%M%S).log"

echo "=============================================="
echo "CellxGene Metadata Collection"
echo "Started: $(date)"
echo "Log: $LOG_FILE"
echo "=============================================="

# 创建虚拟环境（如果不存在）
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "Installing dependencies..."
pip install -q pandas requests cellxgene-census

# 运行收集
echo ""
echo "Starting collection pipeline..."
python run_collection.py "$@" 2>&1 | tee "$LOG_FILE"

echo ""
echo "=============================================="
echo "Collection Complete!"
echo "Ended: $(date)"
echo "Output: data/processed/"
echo "Log: $LOG_FILE"
echo "=============================================="

# 显示结果
if [ -d "data/processed" ]; then
    echo ""
    echo "Generated files:"
    ls -lh data/processed/
fi
