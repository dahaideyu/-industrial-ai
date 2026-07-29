# 知识库管理模块 — 部署指南

本文档覆盖知识库管理模块在 Windows 和 Linux 环境下的部署流程。

---

## 架构概览

知识库管理模块依赖以下基础设施服务：

| 服务 | 用途 | 默认端口 |
|------|------|----------|
| PostgreSQL | 元数据存储（知识库、文档、计划等） | 5432 |
| Redis | Celery 消息队列 + 缓存 | 6379 |
| MinIO | 原始文档对象存储 | 9000（API）/ 9001（控制台） |
| LibreOffice | Office 文档格式转换 | 2002（内部） |
| Celery Worker | 异步任务执行（转换、提取、审核、同步） | — |

> **注意**：文档内容提取已从 Apache Tika 切换为 **MarkItDown + RapidOCR**，纯 Python ONNX 推理，无需 tesseract / poppler 等外部二进制依赖。
>
> 合规性文档（公章/签名/有效期检测）使用视觉模型（qwen-vl-plus），需配置 `DASHSCOPE_API_KEY`。

---

## 一、Windows Docker Desktop 部署

### 1.1 前置条件

1. 安装 [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)，启用 WSL2 后端。
2. 确认 Docker 和 Docker Compose 可用：

```bash
docker --version
docker compose version
```

3. 克隆项目并进入目录：

```bash
git clone <repo-url> chaowei-agent
cd chaowei-agent
```

### 1.2 配置环境变量

复制并编辑配置文件：

```bash
cp config/env/.env.example .env
```

在 `.env` 中确保以下配置：

```bash
# 启用知识库管理模块
ENABLE_KNOWLEDGE_BASE=true

# PostgreSQL（知识库专用）
KNB_PG_HOST=knb-postgresql
KNB_PG_PORT=5432
KNB_PG_DB=knowledge_base
KNB_PG_USER=knb_user
KNB_PG_PASSWORD=your-secure-password

# Redis
KNB_REDIS_URL=redis://knb-redis:6379/1

# MinIO 对象存储
KNB_MINIO_ENDPOINT=knb-minio:9000
KNB_MINIO_ACCESS_KEY=minioadmin
KNB_MINIO_SECRET_KEY=your-secure-password
KNB_MINIO_BUCKET=knowledge-base

# AI 审核（DeepSeek）
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# RAGFlow（可选，用于文档切片和向量化）
RAGFLOW_API_URL=http://your-ragflow-server:9380
RAGFLOW_API_KEY=your-ragflow-key
RAGFLOW_EMBEDDING_MODEL=text-embedding-v4@Tongyi-Qianwen

# 合规性视觉检测（qwen-vl-plus，需要 DashScope API）
DASHSCOPE_API_KEY=sk-your-key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VISION_MODEL=qwen-vl-plus

# 上游 AQA MySQL（同步设备类型用）
AQA_MYSQL_HOST=CHANGE_ME
AQA_MYSQL_PORT=3306
AQA_MYSQL_USER=zxzz
AQA_MYSQL_PASSWORD=your-aqa-password
AQA_MYSQL_DATABASE=jxcw

# 知识库首页展示基地
KNB_LOCATION=江西基地

# 知识库同步 API Key（外部系统同步设备类型时使用）
KNB_SYNC_API_KEY=changeme
KNB_SYNC_ENABLED=true
```

### 1.3 启动基础设施服务

启动知识库管理所需的基础设施：

```bash
docker compose up -d redis minio
```

等待所有服务就绪（约 30 秒），检查状态：

```bash
docker compose ps
```

确认所有服务状态为 `healthy` 或 `running`。

### 1.4 启动 Celery Worker

```bash
docker compose up -d knb-celery-worker
```

查看 Worker 日志确认启动成功：

```bash
docker compose logs -f knb-celery-worker
```

应看到 `celery@... ready` 字样。

### 1.5 启动后端

```bash
ENABLE_KNOWLEDGE_BASE=true uv run uvicorn backend.app:app --host 0.0.0.0 --port 9300
```

或使用一键启动脚本：

```bash
# Windows
set ENABLE_KNOWLEDGE_BASE=true
start.bat

# Linux/Mac
ENABLE_KNOWLEDGE_BASE=true ./start.sh
```

### 1.6 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 `http://localhost:5173`，API 代理到 `http://localhost:9300`。

---

## 二、Linux 服务器部署

### 2.1 前置条件

1. 安装 Docker 和 Docker Compose：

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登录使 docker 组生效
```

2. 克隆项目：

```bash
git clone <repo-url> chaowei-agent
cd chaowei-agent
```

### 2.2 配置环境变量

```bash
cp config/env/.env.example .env
vim .env
```

配置内容同上（1.2 节），注意将密码替换为安全值。

### 2.3 一键启动所有服务

```bash
docker compose up -d
```

此命令会启动：
- 知识库管理基础设施（PostgreSQL、Redis、MinIO、LibreOffice）
- Celery Worker
- 主应用（chaowei-agent，含前后端）

### 2.4 验证部署

```bash
# 检查所有容器状态
docker compose ps

# 检查后端健康
curl http://localhost:9300/api/health

# 检查知识库管理 API
curl http://localhost:9300/api/knowledge-management/bases
```

浏览器访问 `http://your-server-ip:9300` 即可使用。

---

## 三、端口说明

| 端口 | 服务 | 说明 |
|------|------|------|
| 9300 | 主应用（Nginx） | 前端 + 后端 API 统一入口 |
| 5432 | PostgreSQL | 知识库元数据（仅内部访问） |
| 6379 | Redis | 消息队列 + 缓存（仅内部访问） |
| 9000 | MinIO API | 对象存储 API（仅内部访问） |
| 9001 | MinIO Console | 对象存储管理界面（可选暴露） |

> 生产环境建议仅暴露 9300 端口，其余服务通过 Docker 内部网络访问。

---

## 四、服务健康检查

### 检查各服务状态

```bash
# 查看所有容器状态
docker compose ps

# 查看特定服务日志
docker compose logs -f knb-postgresql
docker compose logs -f knb-redis
docker compose logs -f knb-minio
docker compose logs -f knb-celery-worker
docker compose logs -f chaowei-agent
```

### MinIO 控制台

访问 `http://localhost:9001`（或服务器 IP），使用配置的 `KNB_MINIO_ACCESS_KEY` 和 `KNB_MINIO_SECRET_KEY` 登录。

### PostgreSQL 连接测试

```bash
docker compose exec knb-postgresql psql -U knb_user -d knowledge_base -c "\dt"
```

### 知识库管理模块诊断脚本

`docker/scripts/diagnose_knb.py` 自动检查知识库管理模块的所有依赖（PG、Redis、MinIO、AQA MySQL、Celery 任务注册、数据库表结构、数据完整性）。**部署后**或**出现异常**时推荐先跑一遍：

```bash
# 1. 拷贝诊断脚本进容器
docker cp /home/zxzz/project/chaowei-agent/docker/scripts/diagnose_knb.py chaowei-agent-test:/app/diagnose_knb.py

# 2. 运行诊断
docker exec chaowei-agent-test python /app/diagnose_knb.py
```

如果容器名不同（如 `chaowei-agent`），替换为实际容器名即可：

```bash
docker ps | grep chaowei   # 查看实际容器名
docker cp docker/scripts/diagnose_knb.py <容器名>:/app/diagnose_knb.py
docker exec <容器名> python /app/diagnose_knb.py
```

诊断脚本会输出每个检查项的 ✅/❌ 状态和具体错误信息，常见问题包括：

| 错误 | 含义 | 处理 |
|------|------|------|
| ❌ PG 连接失败 | PG 服务不可达或密码错误 | 检查 `KNB_PG_*` 配置 |
| ❌ 缺少 knb_* 表 | 数据库未初始化 | 重启后端自动迁移 |
| ❌ 知识库数量为 0 | 未创建任何 KB | 调用「同步设备类型」API 或手动新建 |
| ❌ AQA MySQL 不可达 | 容器内访问不到 `AQA_MYSQL_HOST` | 改用 `host.docker.internal` 或同网段 IP |
| ❌ Celery 任务未注册 | 包含新任务的 worker 未重启 | 重启 `knb-celery-worker` 容器 |
| ❌ 视觉模型未配置 | 缺 `DASHSCOPE_API_KEY` | 在 `.env` 中补全 |

---

## 五、常见问题排查

### 5.1 Celery Worker 无法连接 Redis

**症状**：Worker 日志显示 `Connection refused`。

**排查**：
```bash
docker compose ps knb-redis
docker compose logs knb-redis
```

**解决**：确认 Redis 容器正常运行，检查 `KNB_REDIS_URL` 配置是否正确。

### 5.2 文档上传后无法提取内容

**症状**：文档状态卡在 `extracting`。

**排查**：
```bash
docker compose logs knb-celery-worker
```

**解决**：
- 检查 Celery Worker 日志中的错误信息
- 确认 LibreOffice 服务正常运行（用于 Office 文档转换）
- 检查 MinIO 连接是否正常（下载原文件）

### 5.3 MinIO 连接失败

**症状**：上传文档时报错 `MinIO connection error`。

**排查**：
```bash
docker compose logs knb-minio
curl http://localhost:9000/minio/health/live
```

**解决**：
- 确认 MinIO 容器正常运行
- 检查 `KNB_MINIO_ENDPOINT`、`KNB_MINIO_ACCESS_KEY`、`KNB_MINIO_SECRET_KEY`

### 5.4 数据库表不存在

**症状**：API 返回 `relation "knowledge_base" does not exist`。

**解决**：后端启动时会自动创建表。如果跳过了初始化，手动触发：

```bash
docker compose restart chaowei-agent
```

或检查日志中是否有 `知识库管理模块数据库初始化完成` 字样。

### 5.5 LibreOffice 转换失败

**症状**：Office 文档转换超时。

**排查**：
```bash
docker compose logs industrial-ai    # 预览接口报错看这里
docker compose logs knb-celery-worker  # 文档转换任务报错看这里
```

**解决**：
- LibreOffice 已内置在 `industrial-ai`/`knb-celery-worker` 镜像中，随容器进程调用，无需额外部署或配置
- 如果内存不足，增加 Docker 内存限制（建议至少 4GB）

### 5.6 首页无数据（基地名、车间、设备类型都为空）

**症状**：进入知识库首页，基地名、车间列表、设备类型都为空，仅"历史沉淀知识库"占位卡可见。点击「同步设备类型」报 `Token 无效或已过期`。

**根因分析**：token 错误往往是表象，**真正原因**通常是后端 `dashboard_base` 或 `sync_device_types` 在连接 **AQA MySQL** 时失败，抛 500 被前端 axios 拦截器兜底为"Token 无效"。

**排查步骤**：

1. **运行诊断脚本**（最快路径）：
   ```bash
   docker cp docker/scripts/diagnose_knb.py <后端容器>:/app/diagnose_knb.py
   docker exec <后端容器> python /app/diagnose_knb.py
   ```
   看 `AQA MySQL 不可达` 是否标 ❌。

2. **检查后端启动日志**：
   ```bash
   docker logs <后端容器> 2>&1 | grep -E "ERROR|sync|AQA|MySQL"
   ```
   若看到 `pymysql.err.OperationalError` 说明 AQA 连不上。

3. **验证 AQA MySQL 在容器内可达**：
   ```bash
   docker exec <后端容器> sh -c "apk add mysql-client && mysql -h$AQA_MYSQL_HOST -P$AQA_MYSQL_PORT -u$AQA_MYSQL_USER -p$AQA_MYSQL_PASSWORD -e 'SELECT 1'"
   ```

**解决**：
- **容器内无法访问宿主机 IP**（如 `CHANGE_ME`）：把 `AQA_MYSQL_HOST` 改为 `host.docker.internal`（Docker Desktop）或同网段 IP（Linux docker network）
- **AQA MySQL 没同步 devicetype 表**：跑 AQA 端的 `dev_device_type` 数据初始化
- **RAGFlow 连不上**：检查 `RAGFLOW_API_URL` 和 `RAGFLOW_API_KEY` 是否正确，否则 KB 创建会失败但不会抛 500

### 5.7 历史沉淀知识库自动出现

**现象**：首次启动后看到「历史沉淀知识库」卡片，但其他 KB 类型都没有。

**说明**：这是**预期行为**。`_create_history_plan` 会在每个设备 KB 下创建一个 `pending` 状态的历史沉淀计划占位，等数据接入后会自动填充。如单独出现一个没有任何设备类型的"历史沉淀 KB"卡，说明 sync 失败但 history 初始化成功——参见 5.6。

---

## 六、生产环境建议

1. **密码安全**：所有默认密码（PostgreSQL、MinIO）必须修改。
2. **网络隔离**：仅暴露 9300 端口，其余服务使用 Docker 内部网络。
3. **数据持久化**：确保 Docker volume 挂载到持久化存储。
4. **备份策略**：定期备份 PostgreSQL 和 MinIO 数据。
5. **资源限制**：在 `docker-compose.yml` 中为各服务设置 CPU 和内存限制。
6. **日志收集**：配置日志驱动将容器日志发送到集中式日志系统。
