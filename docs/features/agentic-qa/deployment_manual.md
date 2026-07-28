# 工业数据智能问答平台 — Docker 部署手册

## 目录

- [部署架构](#部署架构)
- [环境要求](#环境要求)
- [项目文件说明](#项目文件说明)
- [快速部署](#快速部署)
- [配置说明](#配置说明)
- [数据持久化](#数据持久化)
- [常用运维操作](#常用运维操作)
- [备份与恢复](#备份与恢复)
- [故障排查](#故障排查)
- [附录：部署文件清单](#附录部署文件清单)

---

## 部署架构

```
                    ┌───────────────────────────────────┐
                    │       Docker Host (Linux)          │
                    │                                    │
  Client ──→ port 80│  ┌────────────────────────────┐   │
                    │  │   容器 (chaowei-qa-platform) │   │
                    │  │                              │   │
                    │  │  Nginx (port 80)             │   │
                    │  │    ├─ 前端静态资源             │   │
                    │  │    ├─ /api/* → uvicorn :8001 │   │
                    │  │    └─ /api/ws/* → WS         │   │
                    │  │              │               │   │
                    │  │  Uvicorn (port 8001, 内部)   │   │
                    │  │    ├─ FastAPI                │   │
                    │  │    ├─ LangGraph Agent         │   │
                    │  │    └─ Vanna NL2SQL           │   │
                    │  │              │               │   │
                    │  │  Supervisor (进程管理)        │   │
                    │  └────────────────────────────┘   │
                    │              │                     │
                    │  ┌───────────▼─────────────────┐   │
                    │  │  持久化存储 (Docker Volumes) │   │
                    │  │  - vanna-knowledge/         │   │
                    │  │  - entity-knowledge/        │   │
                    │  │  - bge-model/               │   │
                    │  │  - logs/                    │   │
                    │  └─────────────────────────────┘   │
                    └───────────────────────────────────┘
                                │
            ┌───────────────────┼───────────────────┐
            ▼                   ▼                    ▼
      MySQL (外部)       RAGFlow (外部)       DeepSeek API
      10.1.2.227:3306   10.1.2.232:9380      api.deepseek.com
```

**设计要点：**

- **单容器部署**：Nginx + Uvicorn 由 Supervisor 统一管理，简化部署和运维
- **单端口暴露**：仅暴露 80 端口，Nginx 作为统一入口处理静态资源和 API 代理
- **进程管理**：Supervisor 管理 Nginx 和 Uvicorn 两个进程，自动重启
- **向量数据**（ChromaDB）和**嵌入模型**通过 Docker Volume 持久化到宿主机
- **MySQL**、**RAGFlow**、**DeepSeek API** 作为外部服务，通过环境变量配置连接

---

## 环境要求

### 服务器配置

| 项目 | 最低要求 | 推荐配置 |
|------|----------|----------|
| 操作系统 | Linux (Ubuntu 20.04+ / CentOS 7+) | Ubuntu 22.04 LTS |
| CPU | 2 核 | 4 核+ |
| 内存 | 4 GB | 8 GB+ |
| 磁盘 | 20 GB | 50 GB+ (留空间给向量数据增长) |
| 网络 | 可访问 MySQL、RAGFlow、DeepSeek API | — |

### 软件依赖

服务器上需要预先安装：

- **Docker** 24.0+
- **Docker Compose** 2.0+ (`docker compose` 插件或 `docker-compose` 命令)

安装 Docker：

```bash
# Ubuntu
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER
# 重新登录使权限生效

# 验证安装
docker --version
docker compose version
```

---

## 项目文件说明

部署需要将以下文件上传到服务器：

```
chaowei-agent/
├── backend/                    # 后端代码
├── frontend/                   # 前端代码
├── docker/                     # Docker 部署文件 (统一镜像)
│   ├── Dockerfile              # 多阶段构建 (Node + Python + Nginx)
│   ├── docker-compose.yml      # 基础服务编排
│   ├── docker-compose.prod.yml # 生产环境配置
│   ├── docker-compose.test.yml # 测试环境配置
│   ├── docker-compose.shandong.yml # 山东客户环境
│   ├── docker-compose.jiangxi.yml  # 江西客户环境
│   ├── .dockerignore           # 构建忽略文件
│   ├── nginx/nginx.conf        # Nginx 配置
│   └── scripts/                # 部署和启动脚本
├── config/                     # 配置文件 (graph_mapping.yaml, .env 模板)
├── pyproject.toml              # uv 依赖管理
└── .env                        # 环境变量 (需根据实际环境创建)
```

---

## 快速部署

### 第一步：准备项目文件

将整个项目目录上传到服务器的 `/path/chaowei-ai-qa-platform/`（或其他目录）：

```bash
# 方式一：使用 rsync
rsync -avz --exclude 'node_modules' --exclude '__pycache__' --exclude 'logs' \
  ./chaowei-ai-qa-platform/ user@your-server:/opt/chaowei-ai-qa-platform/

# 方式二：使用 scp
scp -r ./chaowei-ai-qa-platform user@your-server:/opt/
```

### 第二步：配置环境变量

编辑 `.env` 文件，填写实际的连接信息：

```bash
cd /opt/chaowei-ai-qa-platform
vim .env
```

必须修改的配置项：

```env
# ===== 必须修改 =====
DEEPSEEK_API_KEY=sk-REDACTED
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

AQA_MYSQL_HOST=your-mysql-host
AQA_MYSQL_PORT=3306
AQA_MYSQL_USER=your-db-user
AQA_MYSQL_PASSWORD=your-db-password
AQA_MYSQL_DATABASE=jxcw

RAGFLOW_BASE_URL=http://your-ragflow-host:9380
RAGFLOW_API_KEY=your-ragflow-key

# ===== 通常保持默认 =====
AQA_VANNA_MODEL=deepseek
AQA_VANNA_CHROMA_PATH=./backend/data/agentic_qa/vanna-knowledge
AQA_APP_ENV=production
AQA_APP_SECRET_KEY=generate-a-random-secret-key-here
```

### 第三步：准备中文嵌入模型

系统使用 BAAI/bge-small-zh-v1.5 中文嵌入模型。将模型目录放到 `backend/services/agentic_qa/bge-small-zh-v1.5/` 即可，Docker 会通过 bind mount 挂载：

```bash
# 在服务器项目目录下放置模型
cd /project/chaowei-ai-qa-platform

# 方式一：从本地上传已有模型
scp -r ./backend/services/agentic_qa/bge-small-zh-v1.5/ user@server:/project/chaowei-ai-qa-platform/

# 方式二：在服务器上下载
pip install sentence-transformers
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5', cache_folder='/project/chaowei-ai-qa-platform/bge-small-zh-v1.5')"

# 确认模型文件存在
ls backend/services/agentic_qa/bge-small-zh-v1.5/
```

> 如果模型目录不存在或为空，系统会降级使用英文模型 `all-MiniLM-L6-v2`，中文语义效果较差。

### 第四步：构建并启动

```bash
cd /opt/chaowei-agent

# 普通模式 (不含 SQL-QA)
docker compose -f docker/docker-compose.yml up -d

# 启用 SQL-QA
ENABLE_SQL_QA=true docker compose -f docker/docker-compose.yml up -d

# 生产环境 (多配置叠加)
ENABLE_SQL_QA=true docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d

# 指定客户环境
docker compose -f docker/docker-compose.yml -f docker/docker-compose.shandong.yml up -d

# 查看服务状态
docker compose -f docker/docker-compose.yml ps

# 查看日志
docker compose -f docker/docker-compose.yml logs -f
```

### 第五步：验证部署

```bash
# 健康检查
curl http://localhost:80/api/health

# 预期返回：
# {"status": "ok", "message": "...", "vanna_agent": "ready"}
```

在浏览器中访问 `http://<服务器IP>` 即可打开平台界面。

---

## 配置说明

### docker-compose.yml 结构

```yaml
services:
  chaowei-agent:    # 单容器: Nginx (80) + Uvicorn (内部), Supervisor 管理
    build:
      args:
        VITE_ENABLE_SQL_QA: "${ENABLE_SQL_QA:-false}"  # 前端构建时注入
    environment:
      - ENABLE_SQL_QA=${ENABLE_SQL_QA:-false}           # 后端运行时读取
```

前端和后端都需要 `ENABLE_SQL_QA`——前端构建时决定是否编译 SQL-QA 页面，后端运行时决定是否加载 SQL-QA 路由。

### 功能开关

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ENABLE_SQL_QA` | 启用 SQL 智能问答 | `false` |
| `ENABLE_REPORT_SCHEDULER` | 启用报告自动调度 | `false` |
| `AGENTIC_MODE` | 启用 ReAct 编排模式 | `on` |

**启用 SQL-QA 的 Docker 命令：**

```bash
# 开发环境
ENABLE_SQL_QA=true docker compose -f docker/docker-compose.yml up -d

# 生产环境
ENABLE_SQL_QA=true docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d
```

### 环境变量参考

| 变量 | 说明 | 示例 |
|------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | `sk-xxx` |
| `DEEPSEEK_BASE_URL` | API 地址 | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 模型名称 | `deepseek-v4-flash` |
| `MYSQL_HOST` | MySQL 主机地址 | `10.1.2.227` |
| `MYSQL_PORT` | MySQL 端口 | `3306` |
| `MYSQL_USER` | 数据库用户名 | `zxzz` |
| `MYSQL_PASSWORD` | 数据库密码 | `your-password` |
| `MYSQL_DATABASE` | 数据库名 | `jxcw` |
| `RAGFLOW_API_URL` | RAGFlow 服务地址 | `http://10.1.2.232:9380` |
| `RAGFLOW_API_KEY` | RAGFlow API 密钥 | `ragflow-xxx` |
| `RAGFLOW_CHAT_ID` | RAGFlow 聊天助手 ID | `xxx` |
| `NEO4J_URI` | Neo4j 图数据库地址 | `neo4j://10.1.2.232:7687` |
| `NEO4J_USER` | Neo4j 用户名 | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j 密码 | `your-password` |
| `APP_ENV` | 运行环境 | `production` |
| `APP_SECRET_KEY` | 应用密钥 | `random-string` |

### 端口映射

| 端口 | 用途 | 对外暴露 |
|------|------|----------|
| 80 | Nginx 统一入口 | 是 (映射到 9300) |
| 9300 | 宿主机访问端口 | 是 |

如需修改对外端口，编辑 `docker-compose.yml` 中 `ports` 配置。

---

## 数据持久化

以下目录通过 Docker Volume 挂载到宿主机，容器删除后数据不会丢失：

| 存储 | 容器内路径 | 宿主机路径 | 内容 |
|--------|-----------|-----------|------|
| bind mount | `/app/backend/data/agentic_qa/vanna-knowledge` | `./backend/data/agentic_qa/vanna-knowledge/` (项目目录) | Vanna 记忆库 |
| bind mount | `/app/backend/data/agentic_qa/entity-knowledge` | `./backend/data/agentic_qa/entity-knowledge/` (项目目录) | 实体索引 + 别名 + 指标 |
| bind mount (只读) | `/app/backend/services/agentic_qa/bge-small-zh-v1.5` | `./backend/services/agentic_qa/bge-small-zh-v1.5/` (项目目录) | 中文嵌入模型 |
| bind mount | `/app/backend/data/agentic_qa/system_data` | `./backend/data/agentic_qa/system_data/` (项目目录) | 应用数据库 (用户/会话/消息) |
| bind mount | `/app/logs/agentic-qa` | `./logs/agentic-qa/` (项目目录) | 应用日志 |

这些 volume 默认由 Docker 管理，存储在 `/var/lib/docker/volumes/` 下。

### 备份持久化数据

```bash
cd /opt/chaowei-ai-qa-platform

# 备份向量数据（直接备份 bind mount 目录）
tar -czf vanna-knowledge-backup-$(date +%Y%m%d).tar.gz ./backend/data/agentic_qa/vanna-knowledge/
tar -czf entity-knowledge-backup-$(date +%Y%m%d).tar.gz ./backend/data/agentic_qa/entity-knowledge/
```

详细备份恢复步骤见[备份与恢复](#备份与恢复)章节。

---

## 常用运维操作

### 服务管理

```bash
# 启动
docker compose -f docker/docker-compose.yml up -d

# 启用 SQL-QA 启动
ENABLE_SQL_QA=true docker compose -f docker/docker-compose.yml up -d

# 停止
docker compose -f docker/docker-compose.yml down

# 重启
docker compose -f docker/docker-compose.yml restart

# 查看状态 + 资源
docker compose -f docker/docker-compose.yml ps && docker stats
```

### 日志查看

```bash
# 实时日志
docker compose -f docker/docker-compose.yml logs -f --tail=100

# 容器内应用日志
docker compose -f docker/docker-compose.yml exec chaowei-agent ls /app/logs/
```

### 更新部署

```bash
cd /opt/chaowei-agent
git pull
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
```

### 进入容器调试

```bash
docker compose -f docker/docker-compose.yml exec chaowei-agent bash
```

---

## 备份与恢复

### 完整备份

```bash
#!/bin/bash
# backup.sh - 完整备份脚本

BACKUP_DIR="/opt/backups/chaowei-qa"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR/$DATE"

# 1. 备份持久化数据
docker compose -f docker/docker-compose.yml stop chaowei-agent  # 暂停服务确保数据一致
tar -czf "$BACKUP_DIR/$DATE/vanna-knowledge.tar.gz" ./backend/data/agentic_qa/vanna-knowledge/
tar -czf "$BACKUP_DIR/$DATE/entity-knowledge.tar.gz" ./backend/data/agentic_qa/entity-knowledge/
tar -czf "$BACKUP_DIR/$DATE/data.tar.gz" ./backend/data/agentic_qa/system_data/
docker compose -f docker/docker-compose.yml start chaowei-agent

# 2. 备份配置文件
cp .env "$BACKUP_DIR/$DATE/.env"
cp docker/docker-compose.yml "$BACKUP_DIR/$DATE/"
cp docker/nginx/nginx.conf "$BACKUP_DIR/$DATE/"

echo "备份完成: $BACKUP_DIR/$DATE"
```

### 恢复数据

```bash
#!/bin/bash
# restore.sh - 恢复备份脚本

BACKUP_PATH="$1"  # 备份目录路径

if [ -z "$BACKUP_PATH" ]; then
    echo "用法: bash restore.sh /opt/backups/chaowei-qa/20260515_120000"
    exit 1
fi

# 停止服务
cd /opt/chaowei-ai-qa-platform
docker compose -f docker/docker-compose.yml down

# 恢复持久化数据
tar -xzf "$BACKUP_PATH/vanna-knowledge.tar.gz"
tar -xzf "$BACKUP_PATH/entity-knowledge.tar.gz"
tar -xzf "$BACKUP_PATH/data.tar.gz"

# 重新启动
docker compose -f docker/docker-compose.yml up -d
echo "恢复完成"
```

### 定时备份 (crontab)

```bash
# 每天凌晨 2 点执行备份
0 2 * * * bash /opt/chaowei-ai-qa-platform/backup.sh >> /var/log/chaowei-backup.log 2>&1
```

---

## 故障排查

### 服务无法启动

```bash
# 查看详细错误日志
docker compose -f docker/docker-compose.yml logs

# 检查配置是否正确
docker compose -f docker/docker-compose.yml config

# 检查端口是否被占用
ss -tlnp | grep 80
```

### 问答不准确 / 向量搜索失败

可能原因：嵌入模型未正确加载，降级使用了英文模型。

```bash
# 检查模型是否加载
docker compose -f docker/docker-compose.yml logs | grep -i embedding

# 预期输出：
# Chinese embedding: BAAI/bge-small-zh-v1.5 loaded

# 如果看到 fallback 警告：
# Chinese embedding failed (...), falling back to all-MiniLM-L6-v2
# 说明中文模型文件不完整，需重新下载 bge-small-zh-v1.5 目录
```

### 无法连接 MySQL

```bash
# 从容器内测试 MySQL 连通性
docker compose -f docker/docker-compose.yml exec chaowei-agent python -c "
import pymysql
conn = pymysql.connect(host='your-mysql-host', port=3306, user='user', password='pass', database='jxcw')
print('MySQL 连接成功')
conn.close()
"
```

### 无法连接 RAGFlow

```bash
# 从容器内测试 RAGFlow 连通性
docker compose -f docker/docker-compose.yml exec chaowei-agent curl -s http://your-ragflow-host:9380/api/v1/health
```

### 重建所有向量索引

部署到新环境后（或切换嵌入模型后），需要在管理后台重建索引：

1. 访问 `http://<服务器IP>/#/admin/training`
2. 数据库索引 → 勾选需要的表 → 点击「索引选中表」
3. 实体管理 → 实体工具 → 点击「重建索引」

### 容器内网络问题

如果容器内无法访问外部服务，检查 Docker 网络：

```bash
# 查看网络
docker network ls

# 检查 DNS
docker compose -f docker/docker-compose.yml exec chaowei-agent nslookup your-mysql-host

# 如果需要使用宿主机网络（不推荐）
# 在 docker-compose.yml 中添加 network_mode: "host"
```

---

## 附录：部署文件清单

部署相关文件位于 `docker/` 目录下（`.dockerignore` 在根目录）：

| 文件 | 用途 |
|------|------|
| `docker/Dockerfile` | 多阶段构建镜像 (Node.js + Python + Nginx) |
| `docker/docker-compose.yml` | 服务编排 (单容器) |
| `docker/nginx/nginx.conf` | Nginx 反向代理配置 |
| `docker/scripts/deploy.sh` | 一键部署脚本 |
| `.dockerignore` | 排除不需要打包到镜像的文件（在根目录） |

