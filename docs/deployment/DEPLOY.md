# AI Report 部署指南

> 主方案：Docker（推荐）
> 废弃方案：PM2（见文末）

---

## 快速开始

### 1. 服务器要求

- Docker 20.10+
- Docker Compose v2+
- 内存 ≥ 2GB

```bash
# 安装 Docker（Ubuntu）
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登录终端
```

### 2. 上传项目

```bash
# 方式一：git clone
git clone <仓库地址> /opt/aiReport
cd /opt/aiReport

# 方式二：rsync（排除本地构建产物）
rsync -avz --exclude='node_modules' --exclude='__pycache__' --exclude='.git' \
  --exclude='backend/venv' --exclude='logs' \
  ./ your-server:/opt/aiReport/
```

### 3. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env，填入真实的 API Key 和数据库密码
vim .env
```

### 4. 一键部署

```bash
# 添加执行权限
chmod +x deploy.sh

# 部署测试环境
./deploy.sh test

# 部署生产环境
./deploy.sh prod

# 部署山东环境
./deploy.sh shandong
```

---

## 部署脚本用法

```bash
./deploy.sh [环境] [操作]
```

| 环境 | 说明 | 容器名 | 配置文件 |
|------|------|--------|----------|
| `test` | 测试环境 | chaowei-agent-test | `.env.test` |
| `prod` | 生产环境 | chaowei-agent-prod | `.env.prod` |
| `shandong` | 山东环境 | chaowei-agent-shandong | `.env.prod.shandong` |

| 操作 | 说明 |
|------|------|
| `up` | 构建并启动（默认） |
| `down` | 停止并移除容器 |
| `restart` | 重启 |
| `build` | 仅构建镜像 |
| `logs` | 查看实时日志 |
| `status` | 查看容器状态 |

---

## 手动 Docker Compose 命令

如果不想用脚本，也可以直接用 docker compose：

```bash
# 测试环境
docker compose -f docker-compose.yml -f docker-compose.test.yml -p chaowei-test up -d --build

# 生产环境
docker compose -f docker-compose.yml -f docker-compose.prod.yml -p chaowei-prod up -d --build

# 山东环境
docker compose -f docker-compose.yml -f docker-compose.shandong.yml -p chaowei-shandong up -d --build
```

---

## 日常运维

```bash
# 查看日志
./deploy.sh prod logs

# 重启服务
./deploy.sh prod restart

# 查看容器状态
./deploy.sh prod status

# 进入容器调试
docker exec -it chaowei-agent-prod bash

# 查看容器内日志文件
docker exec -it chaowei-agent-prod cat /app/logs/pm2-out.log

# 更新代码后重新部署
git pull
./deploy.sh prod restart
```

---

## 端口说明

| 端口 | 用途 |
|------|------|
| 9300 | Nginx 对外端口（前端 + API 代理） |
| 80 | 容器内部 Nginx 端口（映射到宿主机 9300） |

> 生产环境建议配合云服务器安全组，只开放 80/443，不要直接暴露 9300。

---

## 环境变量说明

| 变量 | 说明 | 示例 |
|------|------|------|
| `PROVIDER` | 模型供应商 | `deepseek` / `local_qwen3` / `openai` |
| `POSTGRES_HOST` | 数据库地址 | `CHANGE_ME` |
| `RAGFLOW_BASE_URL` | 知识库地址 | `http://192.168.59.18:9380` |
| `UPSTREAM_BASE_URL` | 上游系统地址 | `http://192.168.59.11:18081` |
| `SCHEDULER_ENABLED` | 定时任务开关 | `true` / `false` |

---

## 多环境共存

Docker Compose 使用 `-p` 指定不同项目名，多个环境可以同时运行在一台服务器上：

```bash
# 同时部署测试和生产
./deploy.sh test up
./deploy.sh prod up

# 它们使用不同的容器名，互不影响
docker ps
# chaowei-agent-test   ...
# chaowei-agent-prod   ...
```

---

## 常见问题

### Q: 端口冲突怎么办？

如果 9300 端口被占用，可以修改 override 文件中的端口映射：

```yaml
# docker-compose.prod.yml
ports:
  - "9400:80"  # 改为 9400
```

### Q: 如何查看容器内日志？

```bash
# 实时日志
./deploy.sh prod logs

# 或进入容器
docker exec -it chaowei-agent-prod bash
tail -f /app/logs/pm2-out.log
```

### Q: 如何回滚到上一个版本？

```bash
git log --oneline  # 找到上一个版本的 commit
git checkout <commit-hash>
./deploy.sh prod restart
```

---

## ~~废弃：PM2 部署方案~~

> **以下方案已废弃，请使用 Docker 方案。**
> 保留仅供历史参考。

<details>
<summary>点击展开 PM2 部署方案（废弃）</summary>

### 前置条件

```bash
# 安装 Node.js 20+
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 安装 PM2
sudo npm install -g pm2
```

### 启动

```bash
cd /opt/aiReport

# 构建前端
cd frontend && npm install && npm run build && cd ..

# 启动后端
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

### 配置 Nginx

```bash
sudo cp nginx.conf /etc/nginx/sites-available/aiReport
sudo ln -sf /etc/nginx/sites-available/aiReport /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 切换环境

```bash
pm2 delete aiReport
pm2 start ecosystem.config.js --env deepseek
pm2 save
```

</details>