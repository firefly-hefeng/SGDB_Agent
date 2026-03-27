#!/bin/bash
# 停止采集器

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/collector.pid"

echo "🛑 停止 ArrayExpress Collector..."

if [ ! -f "$PID_FILE" ]; then
    echo "❌ 未找到 PID 文件，采集器可能未运行"
    exit 1
fi

PID=$(cat "$PID_FILE")

# 检查进程是否存在
if ! ps -p "$PID" > /dev/null 2>&1; then
    echo "⚠️  进程不存在 (PID: $PID)"
    rm -f "$PID_FILE"
    exit 0
fi

# 优雅地终止进程
echo "   发送终止信号到 PID: $PID..."
kill "$PID"

# 等待进程结束
COUNTER=0
while ps -p "$PID" > /dev/null 2>&1; do
    sleep 1
    COUNTER=$((COUNTER + 1))
    if [ $COUNTER -ge 10 ]; then
        echo "   进程未响应，强制终止..."
        kill -9 "$PID" 2>/dev/null
        break
    fi
    echo "   等待进程结束... ($COUNTER 秒)"
done

rm -f "$PID_FILE"
echo "✅ 采集器已停止"

# 显示最后几行日志
LOG_FILE="$SCRIPT_DIR/collected_data/collector.log"
if [ -f "$LOG_FILE" ]; then
    echo ""
    echo "📄 最后日志:"
    tail -n 5 "$LOG_FILE" | sed 's/^/   /'
fi
