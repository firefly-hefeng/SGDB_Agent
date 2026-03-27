#!/bin/bash
# Single Cell Portal Collector Run Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PYTHON="${PYTHON:-python3}"
COLLECTOR="src/collector.py"
STATE_FILE=".state.json"
MAX_RETRIES=3
RETRY_DELAY=30

case "${1:-run}" in
    run)
        echo "Starting collector..."
        "$PYTHON" "$COLLECTOR" "${@:2}"
        ;;
    daemon)
        echo "Starting collector in background..."
        nohup "$PYTHON" "$COLLECTOR" "${@:2}" > logs/collector.log 2>&1 &
        echo $! > .runner.pid
        echo "Started (PID: $!)"
        ;;
    stop)
        if [ -f .runner.pid ]; then
            kill $(cat .runner.pid) 2>/dev/null || true
            rm -f .runner.pid
            echo "Stopped"
        fi
        ;;
    status)
        if [ -f "$STATE_FILE" ]; then
            python3 -c "
import json
with open('$STATE_FILE') as f:
    s = json.load(f)
total = s.get('total', 0)
done = len(s.get('done', []))
print(f'Progress: {done}/{total} ({done/total*100:.1f}%)' if total else 'No progress')
"
        else
            echo "No state file"
        fi
        ;;
    *)
        echo "Usage: $0 {run|daemon|stop|status}"
        exit 1
        ;;
esac
