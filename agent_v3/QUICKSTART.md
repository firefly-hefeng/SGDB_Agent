# Agent V3 快速启动指南

## 目录结构 ✓
```
agent_v3/
├── src/              # 后端代码（已集成 V1Parser）
├── api/              # FastAPI 接口
├── web/              # React 前端（保留你的 bug 修复）
├── tests/            # 测试套件
├── config/           # 配置文件
└── data/             # 数据文件
```

## 启动步骤

### 1. 启动后端服务
```bash
cd "/mnt/d/scgb_agent_bak - claude_v1/agent_v3"
python3 run_server.py --port 8000
```

### 2. 启动前端（如需要）
```bash
cd web
npm run dev
```

## 测试

### 基础测试
```bash
python3 test_v3_basic.py
```

### 单元测试
```bash
python3 -m pytest tests/unit/ -v
```

### E2E 测试
```bash
python3 tests/test_phase1_e2e.py
python3 tests/test_phase2_e2e.py
```

## 核心改进

**查询示例：**
- "所有人源单细胞数据" → 正确识别 organism=Homo sapiens ✓
- "小鼠脑组织" → organism=Mus musculus + tissue=brain
- "肺癌免疫研究" → disease=Lung Cancer + free_text=immune

**V1Parser 优势：**
- LLM 智能理解，无需关键词穷举
- 自动中英文翻译
- 理解隐式上下文
- 注入真实数据库值

## 配置

确保 `config/config.yaml` 中配置了 LLM：
```yaml
llm:
  provider: anthropic  # 或 kimi
  api_key: your_key
  model: claude-opus-4
```

## 下一步

1. 用真实 LLM 测试（非 mock）
2. 验证前端功能
3. 运行完整测试套件
4. 部署到生产环境
