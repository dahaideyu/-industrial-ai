# 部署检查清单

> 目标服务器：Ubuntu 20.04+ / CentOS 7+，内存 ≥ 2GB

---

## 1. 服务器基础环境

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装基础工具
sudo apt install -y git curl wget vim net-tools nginx build-essential

# 安装 Python 3 + pip
sudo apt install -y python3 python3-pip python3-venv

# 安装 Node.js 18+（使用官方源）
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# 安装 PM2
sudo npm install -g pm2

# 验证版本
python3 --version   # >= 3.8
node -v             # >= 18
npm -v
pm2 -v
```

---

## 2. 项目上传与目录准备

```bash
# 创建项目目录
sudo mkdir -p /opt/aiReport
sudo chown $USER:$USER /opt/aiReport

# 本地打包上传（在本地项目根目录执行）
# 注意：不要上传 node_modules/ 和 __pycache__/
rsync -avz --exclude='node_modules' --exclude='__pycache__' --exclude='.git' --exclude='dist' \
  ./ your-server:/opt/aiReport/

# 或手动上传后解压
```

**确认服务器目录结构：**
```
/opt/aiReport/
├── backend/
│   ├── app.py
│   ├── ai_analysis/
│   ├── prompts/
│   └── requirements.txt
├── frontend/
│   ├── package.json
│   └── src/
├── ecosystem.config.js
├── .env
└── logs/          # 需要手动创建
```

---

## 3. Python 环境配置

```bash
cd /opt/aiReport

# 创建虚拟环境
python3 -m venv aiReport_env

# 激活
source aiReport_env/bin/activate

# 升级 pip
pip install --upgrade pip

# 安装依赖
pip install -r backend/requirements.txt

# 验证 FastAPI + uvicorn 已安装
pip show fastapi uvicorn

# 退出虚拟环境
deactivate
```

---

## 4. 前端构建

```bash
cd /opt/aiReport/frontend

# 安装依赖
npm install

# 生产构建（生成 dist/ 目录）
npm run build

# 验证 dist/index.html 存在
ls -la dist/
```

---

## 5. 环境变量配置

```bash
cd /opt/aiReport

# 复制示例配置（如尚未创建）
cp .env.example .env

# 编辑 .env，填入真实 API Key 和数据库密码
vim .env
```

**最小可运行配置：**
```env
PROVIDER=deepseek
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_MODEL=deepseek-chat

POSTGRES_HOST=your-db-host
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-password
```

---

## 6. PM2 配置检查

编辑 `ecosystem.config.js`，确认以下路径与实际一致：

```js
module.exports = {
  apps: [{
    name: "aiReport",
    script: "./aiReport_env/bin/python",
    args: "-m uvicorn backend.app:app --host 0.0.0.0 --port 9300 --workers 1",
    cwd: "/opt/aiReport",
    // ...
  }]
};
```

**创建日志目录：**
```bash
mkdir -p /opt/aiReport/logs
```

---

## 7. Nginx 配置

```bash
# 复制配置到 Nginx
sudo cp /opt/aiReport/nginx.conf /etc/nginx/sites-available/aiReport

# 修改 server_name 为你的域名或 IP
sudo vim /etc/nginx/sites-available/aiReport

# 启用站点
sudo ln -sf /etc/nginx/sites-available/aiReport /etc/nginx/sites-enabled/

# 删除默认站点（可选）
sudo rm -f /etc/nginx/sites-enabled/default

# 检查配置语法
sudo nginx -t

# 重载 Nginx
sudo systemctl reload nginx
```

---

## 8. 启动服务

```bash
cd /opt/aiReport

# 使用 PM2 启动（默认使用 env 中的 PROVIDER）
pm2 start ecosystem.config.js

# 或使用指定模型环境
# pm2 start ecosystem.config.js --env deepseek

# 保存 PM2 进程列表
pm2 save

# 设置开机自启
pm2 startup
# 执行 pm2 startup 输出的命令

# 查看状态
pm2 status
pm2 logs aiReport
```

---

## 9. 防火墙配置

```bash
# UFW（Ubuntu）
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# 或 iptables / 云服务器安全组：开放 80 和 443
```

**注意：** 生产环境建议只开放 80/443，**不要直接暴露 9300 端口**（通过 Nginx 反向代理访问）。

---

## 10. 线上测试验证

```bash
# 1. 测试 API 健康检查
curl http://localhost/api/health

# 2. 测试模板列表
curl http://localhost/api/templates

# 3. 测试设备分析模块列表
curl http://localhost/api/device_analysis/modules

# 4. 测试任务接口
curl http://localhost/api/jobs/summary

# 5. 浏览器访问
# http://your-server-ip/dashboard
# http://your-server-ip/report
```

---

## 11. 切换模型供应商

```bash
# 停止当前实例
pm2 delete aiReport

# 以指定环境重新启动
pm2 start ecosystem.config.js --env deepseek
# 或
pm2 start ecosystem.config.js --env local

# 保存
pm2 save
```

---

## 12. 日常维护命令

```bash
# 查看运行状态
pm2 status

# 查看实时日志
pm2 logs aiReport

# 重启服务
pm2 restart aiReport

# 前端更新后重新构建
cd /opt/aiReport/frontend && npm run build
pm2 restart aiReport

# 清理 PM2 日志
pm2 flush

# 查看 Nginx 错误日志
sudo tail -f /var/log/nginx/error.log
```

---

## 部署前自查表

| 检查项 | 状态 |
|--------|------|
| 服务器内存 ≥ 2GB | ☐ |
| Python 3.8+ 已安装 | ☐ |
| Node.js 18+ 已安装 | ☐ |
| PM2 已安装 | ☐ |
| Nginx 已安装 | ☐ |
| `.env` 已配置真实 API Key | ☐ |
| PostgreSQL 可连接 | ☐ |
| `backend/requirements.txt` 已安装 | ☐ |
| 前端 `npm run build` 成功 | ☐ |
| `ecosystem.config.js` 路径正确 | ☐ |
| `logs/` 目录已创建 | ☐ |
| Nginx 配置已测试 `nginx -t` | ☐ |
| 防火墙已开放 80/443 | ☐ |
| 所有 `/api/*` 接口测试通过 | ☐ |
