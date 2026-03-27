#!/bin/bash
# ArrayExpress Collector 启动脚本
# 后台运行，不受终端影响

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查是否已经在运行
if [ -f "collector.pid" ]; then
    PID=$(cat collector.pid)
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️  采集器已经在运行 (PID: $PID)"
        echo "   查看日志: tail -f collected_data/collector.log"
        exit 1
    else
        echo "📝 清理旧的 PID 文件"
        rm -f collector.pid
    fi
fi

# 创建日志目录
mkdir -p collected_data

# 启动时间
START_TIME=$(date '+%Y-%m-%d %H:%M:%S')
echo "🚀 启动 ArrayExpress Collector..."
echo "   开始时间: $START_TIME"
echo "   日志文件: $SCRIPT_DIR/collected_data/collector.log"

# 使用 nohup 后台运行，输出重定向到日志
nohup python3 "$SCRIPT_DIR/ebi_collector.py" >> "$SCRIPT_DIR/collected_data/collector.log" 2>&1 &
PID=$!

# 保存 PID
echo $PID > collector.pid

echo "✅ 采集器已在后台启动"
echo "   PID: $PID"
echo ""
echo "📋 常用命令:"
echo "   查看日志:  ./view_logs.sh"
echo "   检查状态:  ./check_status.sh"
echo "   停止运行:  ./stop_collector.sh"
echo ""
sleep 1

# 显示前 10 行日志
echo "📄 最近日志:"
tail -n 10 "$SCRIPT_DIR/collected_data/collector.log" 2>/dev/null || echo "   (日志正在生成中...)"
