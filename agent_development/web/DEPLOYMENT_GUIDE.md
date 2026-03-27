# SCDB-Agent Web界面部署与使用指南

> 详细说明如何部署和分享您的SCDB-Agent Web界面

---

## 📋 目录

1. [本地使用](#1-本地使用)
2. [局域网分享](#2-局域网分享)
3. [部署到服务器](#3-部署到服务器)
4. [Docker部署](#4-docker部署)
5. [使用教程](#5-使用教程)

---

## 1. 本地使用

### 方式一：直接运行（最简单）

```bash
# 1. 进入项目目录
cd /path/to/scdb_agent_kimi

# 2. 安装依赖
pip install -r web/requirements.txt

# 3. 启动Web服务
cd web
python app.py

# 4. 在浏览器打开
# http://localhost:5000
```

### 方式二：使用启动脚本

```bash
cd web

# 基本启动
python start_server.py

# 指定端口
python start_server.py --port 8080

# 局域网可访问
python start_server.py --host 0.0.0.0 --port 5000

# 调试模式
python start_server.py --debug
```

---

## 2. 局域网分享

### 让同事/同学在同一网络下访问

```bash
cd web

# 启动时绑定到所有网卡
python start_server.py --host 0.0.0.0 --port 5000
```

然后告诉他们您的IP地址：

```bash
# 查看本机IP
# macOS/Linux:
ifconfig | grep "inet " | grep -v 127.0.0.1

# Windows:
ipconfig
```

他们可以通过以下地址访问：
```
http://<您的IP>:5000

# 例如：
http://192.168.1.100:5000
```

### 使用内网穿透（推荐）

如果想让外网用户访问，可以使用内网穿透工具：

#### 方案A: Ngrok（最简单）

```bash
# 1. 安装ngrok
# https://ngrok.com/download

# 2. 注册获取authtoken
ngrok config add-authtoken YOUR_TOKEN

# 3. 启动穿透
ngrok http 5000

# 4. 获得公网地址（例如：https://abc123.ngrok.io）
# 分享给任何人都可以访问！
```

#### 方案B: Cloudflare Tunnel

```bash
# 1. 安装cloudflared
# https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/tunnel-guide/

# 2. 登录
cloudflared tunnel login

# 3. 创建隧道
cloudflared tunnel create scdb-agent

# 4. 启动
cloudflared tunnel route dns scdb-agent scdb.yourdomain.com
cloudflared tunnel run scdb-agent
```

---

## 3. 部署到服务器

### 方案A: 云服务器部署（阿里云/腾讯云/AWS等）

```bash
# 1. 购买云服务器（推荐配置）
# - CPU: 2核+
# - 内存: 4GB+
# - 带宽: 5Mbps+
# - 系统: Ubuntu 20.04/22.04

# 2. SSH连接到服务器
ssh root@your-server-ip

# 3. 安装Python和依赖
apt update
apt install -y python3 python3-pip

# 4. 上传代码（本地执行）
scp -r web/ root@your-server-ip:/opt/scdb-agent/
scp -r src/ root@your-server-ip:/opt/scdb-agent/
scp -r config/ root@your-server-ip:/opt/scdb-agent/

# 5. 服务器上安装依赖
cd /opt/scdb-agent
pip3 install -r web/requirements.txt
pip3 install -r requirements.txt  # 主项目依赖

# 6. 使用Gunicorn生产部署
pip3 install gunicorn gevent

# 7. 创建启动脚本
cat > /opt/scdb-agent/start.sh << 'EOF'
#!/bin/bash
cd /opt/scdb-agent/web
export PYTHONPATH=/opt/scdb-agent:$PYTHONPATH
gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
  -w 4 -b 0.0.0.0:5000 \
  --access-logfile /var/log/scdb-access.log \
  --error-logfile /var/log/scdb-error.log \
  app:app
EOF
chmod +x /opt/scdb-agent/start.sh

# 8. 使用systemd管理
sudo cat > /etc/systemd/system/scdb-agent.service << 'EOF'
[Unit]
Description=SCDB-Agent Web Service
After=network.target

[Service]
User=root
WorkingDirectory=/opt/scdb-agent/web
Environment=PYTHONPATH=/opt/scdb-agent
ExecStart=/usr/local/bin/gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 4 -b 0.0.0.0:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 9. 启动服务
sudo systemctl daemon-reload
sudo systemctl enable scdb-agent
sudo systemctl start scdb-agent

# 10. 查看状态
sudo systemctl status scdb-agent
```

### 方案B: 使用Nginx反向代理（推荐生产环境）

```bash
# 1. 安装Nginx
apt install -y nginx

# 2. 配置Nginx
cat > /etc/nginx/sites-available/scdb-agent << 'EOF'
server {
    listen 80;
    server_name your-domain.com;  # 修改为您的域名

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    location /static {
        alias /opt/scdb-agent/web/static;
        expires 30d;
    }
}
EOF

# 3. 启用配置
ln -s /etc/nginx/sites-available/scdb-agent /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx

# 4. 配置HTTPS (Let's Encrypt)
apt install -y certbot python3-certbot-nginx
certbot --nginx -d your-domain.com
```

---

## 4. Docker部署

### 一键Docker部署

创建 `Dockerfile`:

```dockerfile
FROM python:3.9-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt web/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r web/requirements.txt

# 复制代码
COPY . .

# 设置Python路径
ENV PYTHONPATH=/app

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["python", "web/app.py"]
```

创建 `docker-compose.yml`:

```yaml
version: '3.8'

services:
  scdb-agent:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
      - ./config:/app/config
      - ./logs:/app/logs
    environment:
      - FLASK_ENV=production
    restart: unless-stopped
```

部署命令：

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down
```

---

## 5. 使用教程

### 界面功能导览

```
┌─────────────────────────────────────────────────────────────────────────┐
│  🧬 SCDB-Agent              [检索] [下载] [统计] [扩展]      🟢在线     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ████████████████████  智能检索  ████████████████████                   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────┐  ┌────────┐  │
│  │  输入自然语言查询...                                 │  │  搜索  │  │
│  └──────────────────────────────────────────────────────┘  └────────┘  │
│                                                                         │
│  ⚡ 快捷标签: 肺癌数据 | COVID-19 | 脑组织样本 | 乳腺癌                  │
│                                                                         │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                                         │
│  找到 1,234 条匹配记录  |  耗时 0.85秒  |  [导出] [下载]                │
│                                                                         │
│  ┌────┬──────────────┬────────┬────────┬────────┬────────┬────┐       │
│  │ ☑️ │ 标题         │ 疾病   │ 组织   │ 平台   │ 数据库 │ 👁️ │       │
│  ├────┼──────────────┼────────┼────────┼────────┼────────┼────┤       │
│  │ ☑️ │ Lung cancer..│ Lung   │ Blood  │ 10x    │ GEO    │ 👁️ │       │
│  └────┴──────────────┴────────┴────────┴────────┴────────┴────┘       │
│                                                                         │
│  💭 相关建议: 肺癌免疫治疗 | 肺腺癌 | 肺癌转移                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 功能详解

#### 1️⃣ 智能检索 Tab

**如何搜索数据：**

1. **自然语言输入**
   - 在搜索框中输入描述，例如：
     - "查找肺癌相关的10x Genomics数据"
     - "COVID-19免疫细胞的单细胞研究"
     - "乳腺癌脑转移的测序数据"

2. **使用快捷标签**
   - 点击下方的快捷标签快速查询
   - 支持自定义添加常用查询

3. **查看结果**
   - 查询意图：AI解析您的需求
   - 匹配记录数：找到的数据条数
   - 详细表格：每条数据的信息

4. **筛选数据**
   - 勾选左侧复选框选择需要的数据
   - 点击表头可排序（需后端支持）

#### 2️⃣ 下载管理 Tab

**如何下载数据：**

1. **在检索页面选择数据**
   - 勾选需要下载的记录
   - 点击"下载数据"按钮

2. **配置下载选项**
   - ☑️ 表达矩阵 (matrix) - 推荐
   - ☐ 原始数据 (raw) - 较大
   - ☐ 元数据 (metadata)
   - ☑️ 同时生成下载脚本

3. **查看下载进度**
   - 切换到"下载管理"Tab
   - 实时查看下载进度条
   - 等待下载完成

4. **批量下载（大量数据）**
   - 选择数据后点击"生成脚本"
   - 下载生成的shell脚本
   - 在服务器上运行脚本

#### 3️⃣ 统计分析 Tab

**如何进行统计分析：**

1. 切换到"统计分析"Tab
2. 从下拉框选择字段：
   - 疾病 (disease_standardized)
   - 组织 (tissue_standardized)
   - 平台 (platform_standardized)
   - 数据库 (database_standardized)
3. 查看图表和数据列表

#### 4️⃣ 字段扩展 Tab

**如何创建新字段：**

1. 切换到"字段扩展"Tab
2. 输入字段信息：
   - **字段名称**: `is_immunotherapy_relevant`
   - **字段定义**: "与免疫治疗相关的研究"
   - **判断标准**: "涉及PD-1/PD-L1、CAR-T、免疫检查点等"
3. 点击"开始字段扩展"
4. 等待AI处理完成
5. 新字段可用于后续查询

---

## 🎯 典型使用场景

### 场景1: 导师让找数据

```
导师：帮我找一些肺癌免疫治疗相关的单细胞数据

操作步骤：
1. 打开Web界面
2. 输入："肺癌免疫治疗相关的单细胞数据"
3. 查看结果，勾选合适的数据
4. 点击"下载数据"
5. 等待下载完成
6. 把下载的数据给导师
```

### 场景2: 组会展示

```
需求：展示某疾病的数据分布情况

操作步骤：
1. 搜索该疾病的数据
2. 切换到"统计分析"Tab
3. 选择"疾病"字段
4. 展示图表给组员看
5. 导出图表用于PPT
```

### 场景3: 协作研究

```
需求：和合作者共享数据检索系统

操作步骤：
1. 部署到云服务器
2. 配置域名和HTTPS
3. 给合作者发送网址
4. 他们可以直接使用
5. 大家看到的结果一致
```

---

## 🔧 故障排除

### 问题1: 启动失败

```bash
# 错误：ModuleNotFoundError
# 解决：安装依赖
pip install -r web/requirements.txt

# 错误：Address already in use
# 解决：更换端口
python start_server.py --port 8080
```

### 问题2: 无法访问

```bash
# 检查防火墙
sudo ufw allow 5000

# 检查安全组（云服务器）
# 在控制台开放5000端口

# 检查监听地址
# 必须使用 0.0.0.0 才能外部访问
python start_server.py --host 0.0.0.0
```

### 问题3: 查询超时

```bash
# 检查Kimi API配置
vim config/config.yaml

# 检查网络连接
ping api.moonshot.cn

# 查看日志
tail -f logs/scdb_agent.log
```

---

## 📞 分享您的Web界面

### 方式1: 发送链接

```
嗨，我部署了一个单细胞数据检索系统：
http://your-server-ip:5000

功能：
- 🔍 自然语言搜索
- 📊 数据可视化
- ⬇️ 一键下载
- ✨ AI字段扩展

快来试试吧！
```

### 方式2: 生成二维码

```bash
# 安装qrencode
apt install qrencode

# 生成二维码
qrencode -o scdb-qr.png "http://your-server-ip:5000"

# 手机扫码即可访问
```

### 方式3: 嵌入到网站

```html
<iframe src="http://your-server-ip:5000" 
        width="100%" 
        height="800px"
        frameborder="0">
</iframe>
```

---

## 🚀 进阶配置

### 添加用户认证

```python
# web/app.py 中添加
from flask_httpauth import HTTPBasicAuth

auth = HTTPBasicAuth()

users = {
    "admin": "your-password",
    "user1": "password1"
}

@auth.verify_password
def verify_password(username, password):
    return users.get(username) == password

@app.route('/api/query', methods=['POST'])
@auth.login_required
def execute_query():
    # ...
```

### 自定义主题

编辑 `web/templates/index.html`:

```javascript
tailwind.config = {
    theme: {
        extend: {
            colors: {
                primary: { 
                    500: '#your-color',  // 修改主色
                }
            }
        }
    }
}
```

---

## 📝 最佳实践

1. **开发环境**: 使用 `--debug` 模式
2. **生产环境**: 使用 Gunicorn + Nginx
3. **数据备份**: 定期备份 `data/` 目录
4. **日志监控**: 配置日志轮转
5. **安全**: 配置HTTPS，添加认证

---

## 🎉 总结

您现在有多种方式提供Web界面：

| 方式 | 适用场景 | 难度 |
|------|---------|------|
| 本地运行 | 个人使用 | ⭐ |
| 局域网分享 | 实验室/办公室 | ⭐⭐ |
| 内网穿透 | 临时分享给他人 | ⭐⭐ |
| 云服务器 | 长期对外提供 | ⭐⭐⭐ |
| Docker | 标准化部署 | ⭐⭐ |

选择适合您的方式，让更多人使用您的SCDB-Agent！

---

*部署指南 v1.0*  
*2026年2月*
