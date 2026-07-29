# AI Report 部署手册

## 目录

1. [服务器环境准备](#服务器环境准备)
2. [项目上传与配置](#项目上传与配置)
3. [Python 环境配置](#python-环境配置)
4. [PM2 安装与配置](#pm2-安装与配置)
5. [防火墙配置](#防火墙配置)
6. [服务管理与监控](#服务管理与监控)
7. [切换模型供应商](#切换模型供应商)
8. [故障排查](#故障排查)

---

## 服务器环境准备

### 1.1 系统要求

- 操作系统：Ubuntu 20.04 LTS 或更高版本 / CentOS 7+ / Debian 10+
- 内存：至少 2GB（推荐 4GB+）
- 磁盘：至少 10GB 可用空间
- Python：3.8 或更高版本

### 1.2 更新系统软件包

```bash
# Ubuntu/Debian
sudo apt update && sudo apt upgrade -y

# CentOS/RHEL
sudo yum update -y
```

### 1.3 安装基础工具

```bash
# Ubuntu/Debian
sudo apt install -y git curl wget vim net-tools

# CentOS/RHEL
sudo yum install -y git curl wget vim net-tools
```

### 1.4 安装 Python 3 和 pip

```bash
# Ubuntu/Debian
sudo apt install -y python3 python3-pip python3-venv

# CentOS/RHEL
sudo yum install -y python3 python3-pip python3-venv
```

验证 Python 版本：

```bash
python3 --version
pip3 --version
```

---

## 项目上传与配置

### 2.1 创建项目目录

```bash
sudo mkdir -p /opt/aiReport
sudo chown -R $USER:$USER /opt/aiReport
cd /opt/aiReport
```

### 2.2 上传项目文件

**方式一：使用 Git 克隆（推荐）**

```bash
# 如果项目在 Git 仓库中
git clone <你的仓库地址> .
```

**方式二：使用 SCP 上传**

在本地电脑执行（Windows 可使用 Git Bash 或 PowerShell）：

```bash
# 在本地项目根目录执行
scp -r * user@your-server-ip:/opt/aiReport/
```

**方式三：使用 SFTP 工具**

使用 FileZilla、WinSCP 等工具将项目文件上传到 `/opt/aiReport/`

### 2.3 确认目录结构

上传完成后，目录结构应该如下：

```
/opt/aiReport/
├── backend/
│   ├── app.py
│   ├── ai_analysis/
│   ├── prompts/
│   └── requirements.txt
├── frontend/
│   ├── dist/      # 构建产物（npm run build 生成）
│   └── src/
├── docs/
├── logs/          # 需要创建
├── ecosystem.config.js
├── nginx.conf
└── .env           # 需要配置
```

### 2.4 创建日志目录

```bash
mkdir -p /opt/aiReport/logs
```

### 2.5 配置 .env 文件

复制或编辑 `.env` 文件，填入各模型供应商的 API Key：

```bash
vim /opt/aiReport/.env
```

确保包含以下配置（根据实际情况填写）：

```bash
# DeepSeek
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=sk-your-deepseek-key-here
DEEPSEEK_MODEL=deepseek-chat

# Qwen (阿里云)
QWEN3_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN3_API_KEY=sk-your-qwen-key-here
QWEN3_MODEL=qwen-plus

# OpenAI
OPENAI_BASE_URL=https://api.openai-proxy.org/v1
OPENAI_API_KEY=sk-your-openai-key-here
OPENAI_MODEL=gpt-4

# 本地模型
LOCAL_QWEN3_BASE_URL=http://10.1.1.4:8001/v1
LOCAL_QWEN3_API_KEY=dummy-key
LOCAL_QWEN3_MODEL=qwen3.5-27b
```

### 2.6 确认 ecosystem.config.js 配置

编辑 `ecosystem.config.js`：

```bash
vim /opt/aiReport/ecosystem.config.js
```

确保路径和环境配置正确：

```javascript
module.exports = {
  apps: [{
    name: "aiReport",
    // 使用 uvicorn 启动 FastAPI（ASGI 服务器，支持高并发）
    script: "./aiReport_env/bin/python",
    args: "-m uvicorn backend.app:app --host 0.0.0.0 --port 9300 --workers 1",
    cwd: "/opt/aiReport",
    instances: 1,
    exec_mode: 'fork',
    autorestart: true,
    watch: false,
    max_memory_restart: "2G",
    // 默认使用本地模型
    env: {
      PROVIDER: "local_qwen3"
    },
    // DeepSeek 环境
    env_deepseek: {
      PROVIDER: "deepseek"
    },
    // Qwen 云端环境
    env_qwen: {
      PROVIDER: "qwen3"
    },
    // OpenAI 环境
    env_openai: {
      PROVIDER: "openai"
    },
    // 本地模型环境
    env_local: {
      PROVIDER: "local_qwen3"
    },
    error_file: "./logs/pm2-error.log",
    out_file: "./logs/pm2-out.log",
    log_date_format: "YYYY-MM-DD HH:mm:ss Z",
    merge_logs: true
  }]
};
```

---

## Python 环境配置

### 3.1 创建虚拟环境

```bash
cd /opt/aiReport
python3 -m venv aiReport_env
```

### 3.2 激活虚拟环境

```bash
source aiReport_env/bin/activate
```

激活成功后，命令行提示符前面会出现 `(aiReport_env)`。

### 3.3 安装依赖包

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.4 验证依赖安装

```bash
pip list
```

应该能看到 fastapi、uvicorn、openai 等包。

### 3.5 测试运行（临时）

```bash
cd /opt/aiReport
# 设置 PROVIDER 环境变量测试
PROVIDER=local_qwen3 python -m uvicorn backend.app:app --host 0.0.0.0 --port 9300
```

如果看到以下输出说明启动成功：

```
[配置] 已加载模型配置:
[配置]   供应商: local_qwen3
[配置]   模型: qwen3.5-27b
[配置]   API 地址: http://10.1.1.4:8001/v1
* Running on all addresses (0.0.0.0)
* Running on http://127.0.0.1:8080
```

按 `Ctrl+C` 停止服务。

---

## PM2 安装与配置

### 4.1 安装 Node.js 和 npm

PM2 需要 Node.js 环境：

```bash
# Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# CentOS/RHEL
curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -
sudo yum install -y nodejs
```

验证安装：

```bash
node --version
npm --version
```

### 4.2 安装 PM2

```bash
sudo npm install -g pm2
```

验证安装：

```bash
pm2 --version
```

### 4.3 配置 PM2 开机自启

```bash
pm2 startup
```

执行后会输出一条命令，**复制并执行**那条命令，例如：

```bash
sudo env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u your-user --hp /home/your-user
```

### 4.4 启动应用

```bash
cd /opt/aiReport

# 使用默认环境（local_qwen3）启动
pm2 start ecosystem.config.js

# 或使用指定环境启动
pm2 start ecosystem.config.js --env deepseek
```

### 4.5 保存 PM2 进程列表

```bash
pm2 save
```

---

## 防火墙配置

### 5.1 Ubuntu/Debian (UFW)

```bash
# 允许 SSH
sudo ufw allow 22/tcp

# 允许服务端口 8080
sudo ufw allow 8080/tcp

# 启用防火墙
sudo ufw enable
```

### 5.2 CentOS/RHEL (firewalld)

```bash
# 允许 SSH
sudo firewall-cmd --permanent --add-service=ssh

# 允许服务端口 8080
sudo firewall-cmd --permanent --add-port=8080/tcp

# 重载防火墙
sudo firewall-cmd --reload
```

### 5.3 云服务器安全组

如果使用阿里云、腾讯云等云服务器，还需要在控制台配置安全组规则，开放 80/443 端口。

---

## 服务管理与监控

### 6.1 PM2 常用命令

```bash
# 查看状态
pm2 status

# 查看日志
pm2 logs aiReport
pm2 logs aiReport --lines 100  # 查看最后 100 行
pm2 logs aiReport --err          # 只看错误日志

# 重启服务
pm2 restart aiReport

# 停止服务
pm2 stop aiReport

# 启动服务
pm2 start aiReport

# 删除服务
pm2 delete aiReport

# 查看资源使用情况
pm2 monit

# 查看详细信息
pm2 show aiReport
```

### 6.2 测试服务

#### 测试接口

```bash
# 测试模板列表接口
curl http://localhost/api/templates
```

#### 使用浏览器访问

- 前端页面：`http://your-server-ip/dashboard`
- API 测试：`http://your-server-ip/api/health`

### 6.3 查看应用日志

```bash
# PM2 日志
tail -f /opt/aiReport/logs/pm2-out.log
tail -f /opt/aiReport/logs/pm2-error.log
```

---

## 切换模型供应商

### 方式一：delete + start（推荐，最稳妥）

```bash
# 停止并删除旧实例
pm2 delete aiReport

# 用新环境启动
pm2 start ecosystem.config.js --env deepseek

# 查看日志确认
pm2 logs aiReport
```

### 方式二：配置多实例（零 downtime）

修改 ecosystem.config.js，配置多个应用：

```javascript
apps: [{
  name: "aiReport-deepseek",
  script: "./aiReport_env/bin/python",
  args: "-m uvicorn backend.app:app --host 0.0.0.0 --port 8001 --workers 1",
  env: {
    PROVIDER: "deepseek"
  }
}, {
  name: "aiReport-qwen",
  script: "./aiReport_env/bin/python",
  args: "-m uvicorn backend.app:app --host 0.0.0.0 --port 8002 --workers 1",
  env: {
    PORT: 8002,
    PROVIDER: "qwen3"
  }
}]
```

然后：
```bash
# 全部启动
pm2 start ecosystem.config.js

# 通过 Nginx 或修改前端调用地址切换
```

### 方式三：临时环境变量（测试用）

```bash
# 临时设置环境变量并重启
PROVIDER=qwen3 pm2 restart aiReport --update-env
```

---

## 故障排查

### 7.1 服务无法启动

```bash
# 查看 PM2 日志
pm2 logs aiReport --err

# 检查端口是否被占用
netstat -tlnp | grep 8080

# 手动运行测试
cd /opt/aiReport
source aiReport_env/bin/activate
PROVIDER=local_qwen3 python -m uvicorn backend.app:app --host 0.0.0.0 --port 9300
```

### 7.2 依赖安装失败

```bash
# 确保虚拟环境已激活
source aiReport_env/bin/activate

# 更新 pip
pip install --upgrade pip

# 单独安装包
pip install fastapi uvicorn
pip install openai
```

### 7.3 配置加载失败

**错误："请设置 PROVIDER 环境变量"**

解决：确保启动时设置了 PROVIDER 环境变量

```bash
# 测试时
PROVIDER=local_qwen3 python -m uvicorn backend.app:app --host 0.0.0.0 --port 9300

# PM2 时
pm2 start ecosystem.config.js --env deepseek
```

**错误："请在 .env 文件中配置 XXX_BASE_URL"**

解决：检查 .env 文件中是否有对应的配置项

### 7.4 LLM 连接失败

- 检查 LLM 服务地址是否正确
- 确认服务器能访问 LLM 服务：`ping 10.1.1.4`
- 检查防火墙是否阻止了连接
- 测试 LLM 服务是否正常运行
- 检查 API Key 是否正确

### 7.5 权限问题

```bash
# 确保项目目录权限正确
sudo chown -R $USER:$USER /opt/aiReport
chmod -R 755 /opt/aiReport

# 确保日志目录可写
mkdir -p /opt/aiReport/logs
chmod 755 /opt/aiReport/logs
```

### 7.6 PM2 开机自启不生效

```bash
# 重新设置 startup
pm2 unstartup
pm2 startup
# 执行输出的命令
pm2 save
```

---

## 附录

### A. 快速部署脚本

可以将以下命令保存为 `deploy.sh` 快速部署：

```bash
#!/bin/bash
set -e

# 配置
PROJECT_DIR="/opt/aiReport"
USER=$(whoami)

echo "=== 开始部署 AI Report ==="

# 1. 创建目录
echo "[1/7] 创建项目目录..."
sudo mkdir -p $PROJECT_DIR
sudo chown -R $USER:$USER $PROJECT_DIR
cd $PROJECT_DIR

# 2. 这里需要手动上传项目文件
echo "[2/7] 请上传项目文件到 $PROJECT_DIR"
echo "      按回车继续（确认已上传）..."
read

# 3. 创建虚拟环境
echo "[3/7] 创建 Python 虚拟环境..."
python3 -m venv aiReport_env
source aiReport_env/bin/activate

# 4. 安装依赖
echo "[4/7] 安装 Python 依赖..."
pip install --upgrade pip
pip install -r requirements.txt

# 5. 创建日志目录
echo "[5/7] 创建日志目录..."
mkdir -p logs

# 6. 配置 .env
echo "[6/7] 请配置 .env 文件，填写 API Key"
echo "      按回车继续（确认已配置）..."
read

# 7. 启动服务
echo "[7/7] 启动 PM2 服务..."
pm2 start ecosystem.config.js
pm2 save

echo ""
echo "=== 部署完成 ==="
echo "查看状态: pm2 status"
echo "查看日志: pm2 logs aiReport"
echo "测试访问: curl http://localhost/api/templates"
```

### B. 更新应用流程

```bash
cd /opt/aiReport

# 1. 拉取最新代码（或上传新文件）
git pull
# 或手动上传新文件到 /opt/aiReport

# 2. 激活虚拟环境（仅在需要更新依赖时）
source aiReport_env/bin/activate

# 3. 更新依赖（如 requirements.txt 有变化）
pip install -r requirements.txt

# 4. 重启 PM2 服务
pm2 restart aiReport

# 5. 查看状态和日志
pm2 status
pm2 logs aiReport --lines 50
```

### C. 相关文件路径

| 项目 | 路径 |
|------|------|
| 项目根目录 | `/opt/aiReport` |
| 应用主文件 | `/opt/aiReport/backend/app.py` |
| 虚拟环境 | `/opt/aiReport/aiReport_env` |
| PM2 配置 | `/opt/aiReport/ecosystem.config.js` |
| 环境变量配置 | `/opt/aiReport/.env` |
| 应用日志 | `/opt/aiReport/logs/` |

### D. 支持的模型供应商

| 供应商 | PROVIDER 值 | 说明 |
|--------|------------|------|
| DeepSeek | `deepseek` | 深度求索模型 |
| Qwen (阿里云) | `qwen3` | 阿里云通义千问 |
| OpenAI | `openai` | OpenAI GPT 模型 |
| 本地 Qwen | `local_qwen3` | 本地部署的 Qwen 模型 |

---

## 前端部署

### 构建前端

在开发机或 CI 环境构建前端：

```bash
cd /opt/aiReport/frontend
npm install
npm run build
```

构建产物位于 `frontend/dist/` 目录。

### 方式一：Nginx 托管（推荐）

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        root /opt/aiReport/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://localhost:9300/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 方式二：后端提供静态文件

如需由 FastAPI 提供前端静态文件，在 `backend/app.py` 中配置 `StaticFiles`：

```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
```

> 推荐使用 **Nginx 托管** 方式，性能和并发能力更好。

---

**文档版本**：v3.0
**最后更新**：2026-04-30
