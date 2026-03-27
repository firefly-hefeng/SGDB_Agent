#!/bin/bash
# 持续监控脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/collected_data"
PID_FILE="$SCRIPT_DIR/collector.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
else
    echo "❌ 未找到 PID 文件"
    exit 1
fi

echo "========================================"
echo "  ArrayExpress Collector 实时监控"
echo "========================================"
echo "开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "PID: $PID"
echo "========================================"
echo ""

# 监控循环
COUNT=0
while true; do
    # 检查进程是否存在
    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo ""
        echo "❌ 采集器进程已结束 (PID: $PID)"
        echo "结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
        rm -f "$PID_FILE"
        break
    fi
    
    COUNT=$((COUNT + 1))
    
    # 统计文件
    BS_COUNT=$(ls -1 "$OUTPUT_DIR/raw_biostudies"/*.json 2>/dev/null | wc -l)
    ENA_COUNT=$(ls -1 "$OUTPUT_DIR/raw_ena"/*.json 2>/dev/null | wc -l)
    BIO_COUNT=$(ls -1 "$OUTPUT_DIR/raw_biosamples"/*.json 2>/dev/null | wc -l)
    LOG_SIZE=$(du -h "$OUTPUT_DIR/collector.log" 2>/dev/null | cut -f1)
    
    # 获取进程状态
    PROC_STAT=$(ps -p "$PID" -o etime= 2>/dev/null | tr -d ' ')
    
    # 显示状态
    printf "\r[%3d] %s | BS: %4d | ENA: %4d | BIO: %4d | 运行: %s" \
        "$COUNT" "$(date '+%H:%M:%S')" "$BS_COUNT" "$ENA_COUNT" "$BIO_COUNT" "$PROC_STAT"
    
    # 每 30 秒输出一次详细信息
    if [ $((COUNT % 6)) -eq 0 ]; then
        echo ""
        echo "  [日志大小: $LOG_SIZE]"
    fi
    
    sleep 5
done

echo ""
echo "========================================"
echo "监控结束"
echo "========================================"
