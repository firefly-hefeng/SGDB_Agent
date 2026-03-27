# SCDB-Agent Web界面

SCDB-Agent的现代化Web界面，提供直观的单细胞数据检索和管理功能。

## 功能特性

### 1. 智能检索
- 🔍 自然语言查询输入
- ⚡ 实时查询建议
- 📊 结果统计展示
- 🔗 会话历史追踪

### 2. 数据展示
- 📋 表格形式展示结果
- 🎯 多维度数据筛选
- 👁️ 详情弹窗查看
- 📥 CSV导出功能

### 3. 下载管理
- ⬇️ 一键下载数据
- 📦 批量下载支持
- 📈 实时进度跟踪
- 📝 下载脚本生成

### 4. 统计分析
- 📊 可视化图表
- 📈 字段分布统计
- 🔍 数据洞察分析

### 5. 字段扩展
- ✨ AI驱动字段创建
- 🎨 自定义筛选条件
- 🚀 动态字段管理

## 界面预览

```
┌─────────────────────────────────────────────────────────────┐
│  🧬 SCDB-Agent v2.0                              [已连接]   │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ 智能检索 │ 下载管理 │ 统计分析 │ 字段扩展 │                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   🔍 查找肺癌相关的10x Genomics单细胞数据                    │
│   ┌──────────────────────────────────────────────────┐ 🔍   │
│   │                                                  │     │
│   └──────────────────────────────────────────────────┘     │
│                                                             │
│   ⚡ 快捷: 肺癌数据  COVID-19研究  脑组织样本               │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 找到 1,234 条记录 • 耗时 0.85 秒                     │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                             │
│   ┌──────────┬──────────┬──────────┬──────────┬──────────┐ │
│   │ 标题     │ 疾病     │ 组织     │ 平台     │ 数据库   │ │
│   ├──────────┼──────────┼──────────┼──────────┼──────────┤ │
│   │ ...      │ Lung     │ Blood    │ 10x      │ GEO      │ │
│   └──────────┴──────────┴──────────┴──────────┴──────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
cd web
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 开发模式
python app.py

# 或指定端口
python app.py --port 8080
```

### 3. 访问界面

打开浏览器访问: http://localhost:5000

## API文档

### 基础信息

- **Base URL**: `http://localhost:5000/api`
- **Content-Type**: `application/json`

### 接口列表

#### 1. 健康检查
```http
GET /api/health
```

#### 2. 执行查询
```http
POST /api/query
Content-Type: application/json

{
  "query": "查找肺癌数据",
  "session_id": "optional-session-id",
  "limit": 20
}
```

#### 3. 获取数据库Schema
```http
GET /api/schema
```

#### 4. 字段统计
```http
GET /api/statistics/{field}?top_n=20
```

#### 5. 下载预览
```http
POST /api/download/preview
Content-Type: application/json

{
  "records": [...]
}
```

#### 6. 创建下载任务
```http
POST /api/download/tasks
Content-Type: application/json

{
  "records": [...],
  "file_types": ["matrix"],
  "output_dir": "optional/path"
}
```

#### 7. 开始下载
```http
POST /api/download/start
Content-Type: application/json

{
  "task_ids": ["task-id-1", "task-id-2"]
}
```

#### 8. 生成下载脚本
```http
POST /api/download/script
Content-Type: application/json

{
  "records": [...],
  "file_types": ["matrix"]
}
```

#### 9. 字段扩展
```http
POST /api/field/expand
Content-Type: application/json

{
  "field_name": "is_cancer_immunology",
  "definition": "癌症免疫学相关研究",
  "criteria": "涉及肿瘤免疫微环境、免疫检查点等",
  "session_id": "optional-session-id"
}
```

### WebSocket事件

连接WebSocket: `ws://localhost:5000`

#### 事件列表

| 事件 | 方向 | 说明 |
|------|------|------|
| `connect` | 客户端→服务器 | 连接建立 |
| `query_stream` | 客户端→服务器 | 流式查询请求 |
| `query_result` | 服务器→客户端 | 查询结果 |
| `download_progress` | 服务器→客户端 | 下载进度更新 |
| `download_complete` | 服务器→客户端 | 下载完成通知 |

## 技术栈

### 后端
- **Flask** - Web框架
- **Flask-SocketIO** - WebSocket支持
- **Flask-CORS** - 跨域处理

### 前端
- **Alpine.js** - 响应式框架
- **Tailwind CSS** - 样式框架
- **Chart.js** - 图表库
- **Font Awesome** - 图标库

### 特性
- ✅ 响应式设计，支持移动端
- ✅ 实时通信，进度推送
- ✅ 现代化UI，流畅动画
- ✅ 无需构建步骤，即开即用

## 配置说明

### 环境变量

```bash
# Flask配置
FLASK_ENV=development
FLASK_DEBUG=1
FLASK_PORT=5000

# SocketIO配置
SOCKETIO_CORS_ALLOWED_ORIGINS=*
```

### 配置文件

Web服务读取项目根目录的 `config/config.yaml` 配置文件。

## 开发指南

### 目录结构

```
web/
├── app.py                 # Flask应用主文件
├── requirements.txt       # Python依赖
├── README.md             # 本文档
├── templates/
│   └── index.html        # 主页面模板
└── static/
    ├── css/              # 样式文件（可选）
    ├── js/               # JS文件（可选）
    └── images/           # 图片资源
```

### 添加新页面

1. 在 `index.html` 中添加新Tab内容
2. 在Alpine.js数据对象中添加状态
3. 实现对应的API接口

### 自定义主题

修改 `index.html` 中的Tailwind配置：

```javascript
tailwind.config = {
    theme: {
        extend: {
            colors: {
                primary: { /* 自定义主色 */ },
                secondary: { /* 自定义辅色 */ }
            }
        }
    }
}
```

## 常见问题

### Q1: 如何修改端口？

修改 `app.py` 底部：

```python
socketio.run(app, host='0.0.0.0', port=8080)  # 改为8080
```

### Q2: 如何部署到生产环境？

使用Gunicorn + Gevent：

```bash
pip install gunicorn gevent

gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 -b 0.0.0.0:5000 app:app
```

### Q3: 前端资源如何CDN加速？

修改 `index.html` 中的CDN链接为国内源：

```html
<!-- 替换为 -->
<script src="https://cdn.bootcdn.net/ajax/libs/alpinejs/3.x.x/cdn.min.js"></script>
```

## 更新日志

### v2.0.0 (2026-02)
- ✨ 初始版本发布
- 🔍 智能检索功能
- ⬇️ 下载管理功能
- 📊 统计分析功能
- ✨ 字段扩展功能

---

*SCDB-Agent Web Interface v2.0*  
*Powered by Flask & Alpine.js*
