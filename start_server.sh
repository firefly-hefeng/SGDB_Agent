#!/bin/bash
# Agent V3 启动脚本

cd "/mnt/d/scgb_agent_bak - claude_v1/agent_v3"

export KIMI_API_KEY="sk-UL5YodR7ZL4S9dytpfMWJgmPTXJjkeNSd7Ktq9bbEhElzDfX"

echo "Starting Agent V3 server..."
python3 run_server.py --port 8000

# 访问地址:
# 前端: http://localhost:8000
# API: http://localhost:8000/singledb/scdbAPI/*
# API 文档: http://localhost:8000/docs
