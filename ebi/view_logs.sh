#!/bin/bash
# 查看采集器日志

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/collected_data/collector.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ 日志文件不存在: $LOG_FILE"
    exit 1
fi

echo "📄 实时查看日志 (按 Ctrl+C 退出)..."
echo "========================================"
tail -f "$LOG_FILE"
