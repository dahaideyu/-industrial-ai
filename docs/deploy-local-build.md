# 本地打包部署指南

## 概述

本地构建 Docker 镜像（含 Cython 源码编译 + 提示词加密），导出 tar 上传到服务器部署。服务器上无需源码，只有镜像和配置文件。

## 源码保护机制

| 保护层 | 方式 | 效果 |
|--------|------|------|
| Python 源码 | Cython 编译 `.py` → `.so` | 258 个 .py → 206 个 .so + 52 个 `__init__.py` |
| 提示词模板 | Fernet 加密 → `prompts_encrypted.json` | 48 个明文 .txt → 1 个密文 JSON |
| 配置文件 | 暂未加密 | YAML 明文（后续计划） |
| 环境变量 | `.env` 文件不上传镜像 | 运行时通过 `env_file` 注入 |

> 💡 **双重保护**：解密代码（`prompt_loader.py`）已编译为 `.so`，解密逻辑不可读。单独拿到密钥（`.env`）或单独拿到密文（tar）都无法解密，必须进入运行中的容器才能解密。

## 构建控制参数

通过 `COMPILE_SOURCE` 参数控制是否编译：

| 环境 | COMPILE_SOURCE | 说明 |
|------|---------------|------|
| 本地测试 | `false` | 跳过 Cython 编译，构建快、方便调试 |
| 生产部署 | `true`（默认） | 编译 `.py` → `.so`，删除源码 |

## 部署流程

```
本地：加密提示词 → Docker build（Cython 编译）→ 导出 tar
                        ↓
上传：tar + docker/ 配置目录
                        ↓
服务器：docker load → docker compose up（无需源码）
```

## 详细步骤

### 步骤 1：本地构建

```bash
# 方式一：一键构建脚本（推荐）
build.bat

# 方式二：手动构建
# 1. 加密提示词（生成 backend/prompts_encrypted.json）
python scripts/encrypt_prompts.py

# 2. 构建镜像（COMPILE_SOURCE=true 编译源码）
docker build -f docker/Dockerfile --build-arg COMPILE_SOURCE=true -t chaowei-agent:latest .

# 3. 导出镜像
docker save -o chaowei-agent-latest.tar chaowei-agent:latest
```

### 步骤 2：上传到服务器

```bash
# 上传镜像（3.2GB）
scp chaowei-agent-latest.tar root@服务器IP:/opt/chaowei-agent/

# 上传配置文件
scp -r docker/ root@服务器IP:/opt/chaowei-agent/
```

### 步骤 3：服务器加载并启动

```bash
cd /opt/chaowei-agent

# 加载镜像
docker load -i chaowei-agent-latest.tar

# 启动（以长兴为例）
docker compose -f docker/docker-compose.yml -f docker/docker-compose.changxing.yml up -d

# 查看状态
docker compose -f docker/docker-compose.yml -f docker/docker-compose.changxing.yml ps
docker compose -f docker/docker-compose.yml -f docker/docker-compose.changxing.yml logs -f
```

> **说明**：`image:` 和 `build:` 在 compose 中共存，镜像存在就用镜像，不存在才构建。服务器上 `docker load` 后 compose 直接使用本地镜像。

### 步骤 4：验证部署

```bash
# 健康检查
curl http://localhost:9300/api/health

# 前端页面
curl http://localhost:9300/

# 验证源码已编译保护
docker exec chaowei-agent-changxing find /app/backend -name "*.so" | wc -l
# 预期：200+ .so 文件

docker exec chaowei-agent-changxing find /app/backend -name "*.py" | wc -l
# 预期：约 52 个（全是 __init__.py）

# 验证提示词已加密
docker exec chaowei-agent-changxing find /app/backend -name "*.txt" -path "*/prompts/*" | wc -l
# 预期：0（明文已删除）
```

## 服务器目录结构

```
/opt/chaowei-agent/
├── docker/
│   ├── docker-compose.yml           # 基础 compose
│   ├── docker-compose.changxing.yml # 环境覆盖（env_file 指向对应 .env）
│   ├── docker-compose.jiangxi.yml
│   ├── docker-compose.shandong.yml
│   ├── .env.prod.changxing          # 环境配置（含 PROMPT_ENCRYPT_KEY）
│   ├── .env.prod.jiangxi
│   └── .env.prod.shandong
├── logs/                            # 日志（volume 挂载）
├── data/                            # 数据（volume 挂载）
└── chaowei-agent-latest.tar         # 镜像文件（加载后可删除）
```

> 💡 服务器上**不需要**源码（`backend/`、`config/`、`frontend/`）、Dockerfile、构建脚本。

## 提示词加密密钥

### 密钥生成

```bash
# 运行加密脚本，输出密钥
python scripts/encrypt_prompts.py
# 输出: PROMPT_ENCRYPT_KEY=aHmKQrY-4vZkfLTDjaWbnHxVPbSclw3noU-xw1n_3HE=
```

### 密钥配置

将输出的密钥添加到对应环境的 `.env` 文件中：

```bash
# docker/.env.prod.changxing
PROMPT_ENCRYPT_KEY=aHmKQrY-4vZkfLTDjaWbnHxVPbSclw3noU-xw1n_3HE=
```

容器启动时通过 `env_file` 注入，`prompt_loader` 自动解密提示词。

> ⚠️ 密钥只存于服务器 `.env` 文件中，不在 Docker 镜像里。即使拿到密钥，解密代码（`prompt_loader`）已编译为 `.so` 二进制，外部无法调用解密逻辑。只有运行中的容器内部才能完成解密。

### 密钥更换流程

1. 本地运行 `python scripts/encrypt_prompts.py` 生成新密钥
2. 重新构建镜像（`docker build --build-arg COMPILE_SOURCE=true`）
3. 更新服务器 `.env` 中的 `PROMPT_ENCRYPT_KEY`
4. 上传新 tar + 重新部署

## 后续更新

```bash
# 本地构建新版本
build.bat

# 上传新镜像
scp chaowei-agent-latest.tar root@服务器IP:/opt/chaowei-agent/

# 服务器重新加载
cd /opt/chaowei-agent
docker load -i chaowei-agent-latest.tar
docker compose -f docker/docker-compose.yml -f docker/docker-compose.changxing.yml up -d
```

## 常用命令

### 停止服务

```bash
cd /opt/chaowei-agent
docker compose -f docker/docker-compose.yml -f docker/docker-compose.changxing.yml down
```

### 重启服务

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.changxing.yml restart
```

### 查看日志

```bash
# 实时查看
docker compose -f docker/docker-compose.yml -f docker/docker-compose.changxing.yml logs -f

# 最近 100 行
docker compose -f docker/docker-compose.yml -f docker/docker-compose.changxing.yml logs --tail 100
```

## 环境配置对照表

| 环境 | env 文件 | compose 覆盖文件 | 项目名（-p） |
|------|---------|-----------------|-------------|
| 测试 | `.env.test` | `docker-compose.test.yml` | chaowei-test |
| 长兴 | `.env.prod.changxing` | `docker-compose.changxing.yml` | chaowei-changxing |
| 江西 | `.env.prod.jiangxi` | `docker-compose.jiangxi.yml` | chaowei-jiangxi |
| 山东 | `.env.prod.shandong` | `docker-compose.shandong.yml` | chaowei-shandong |

## 故障排查

### 问题 1：entrypoint.sh 报 `bash\r: No such file or directory`

Windows 换行符问题，修复方法：

```bash
sed -i 's/\r$//' docker/scripts/entrypoint.sh
```

然后重新构建镜像。

### 问题 2：启动后 502 Bad Gateway

后端模块初始化需要时间（30-60 秒），等待后刷新即可。查看日志确认：

```bash
docker logs chaowei-agent-changxing
# 等待出现 "Application startup complete"
```

### 问题 3：提示词解密失败

检查 `.env` 中 `PROMPT_ENCRYPT_KEY` 是否与构建时的密钥一致：

```bash
# 进入容器测试
docker exec chaowei-agent-changxing python -c "
import os; print('PROMPT_ENCRYPT_KEY:', os.getenv('PROMPT_ENCRYPT_KEY', '未设置'))
"
```

### 问题 4：端口冲突

修改对应环境 compose 文件中的端口映射：

```yaml
ports:
  - "9301:80"  # 改为其他端口
```
