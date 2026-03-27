#!/bin/bash
# 检查采集器运行状态

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

OUTPUT_DIR="$SCRIPT_DIR/collected_data"
PID_FILE="$SCRIPT_DIR/collector.pid"

echo "========================================"
echo "  ArrayExpress Collector 状态检查"
echo "========================================"
echo ""

# 检查进程状态
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "✅ 采集器正在运行"
        echo "   PID: $PID"
        # 显示运行时间
        ps -p "$PID" -o pid,etime,cmd 2>/dev/null | tail -n 1
    else
        echo "❌ 采集器未运行 (PID 文件存在但进程不存在)"
        rm -f "$PID_FILE"
    fi
else
    echo "❌ 采集器未运行 (无 PID 文件)"
fi

echo ""
echo "📊 数据收集进度:"
echo "----------------------------------------"

# 检查各类数据文件数量
if [ -d "$OUTPUT_DIR/raw_biostudies" ]; then
    BS_COUNT=$(ls -1 "$OUTPUT_DIR/raw_biostudies"/*.json 2>/dev/null | wc -l)
    echo "  raw_biostudies/:  $BS_COUNT 个文件"
else
    echo "  raw_biostudies/:  0 个文件"
fi

if [ -d "$OUTPUT_DIR/raw_ena" ]; then
    ENA_COUNT=$(ls -1 "$OUTPUT_DIR/raw_ena"/*.json 2>/dev/null | wc -l)
    echo "  raw_ena/:         $ENA_COUNT 个文件"
else
    echo "  raw_ena/:         0 个文件"
fi

if [ -d "$OUTPUT_DIR/raw_biosamples" ]; then
    BIO_COUNT=$(ls -1 "$OUTPUT_DIR/raw_biosamples"/*.json 2>/dev/null | wc -l)
    echo "  raw_biosamples/:  $BIO_COUNT 个文件"
else
    echo "  raw_biosamples/:  0 个文件"
fi

if [ -f "$OUTPUT_DIR/raw_scea.json" ]; then
    echo "  raw_scea.json:     已生成"
else
    echo "  raw_scea.json:     未生成"
fi

echo ""
echo "📄 日志信息:"
echo "----------------------------------------"
if [ -f "$OUTPUT_DIR/collector.log" ]; then
    LOG_SIZE=$(du -h "$OUTPUT_DIR/collector.log" 2>/dev/null | cut -f1)
    echo "  日志大小: $LOG_SIZE"
    echo ""
    echo "  最新 5 条日志:"
    tail -n 5 "$OUTPUT_DIR/collector.log" | sed 's/^/    /'
else
    echo "  暂无日志文件"
fi

# 检查进度文件
if [ -f "$OUTPUT_DIR/progress.json" ]; then
    echo ""
    echo "📋 进度文件: 已创建"
else
    echo ""
    echo "📋 进度文件: 未创建"
fi

echo ""
echo "========================================"
