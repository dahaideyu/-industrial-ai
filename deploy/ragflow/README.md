# RAGFlow 独立部署

跟主项目 `deploy/docker/docker-compose.yml` 完全独立、互不干扰。RAGFlow 官方栈本身较重
（RAGFlow 服务本身 + 文档检索引擎 Elasticsearch/Infinity + MySQL + Redis + MinIO），
资源需求跟主项目/TimescaleDB 不是一个量级（官方建议内存起点较高，还要下模型），
所以单独一个文件夹自己管，不合并进共享 compose 文件。

跟本项目现有的 5 套环境配置（`deploy/docker/.env*`）现状一致：所有环境的 `RAGFLOW_BASE_URL`
从来都是指向一个**外部独立部署的 RAGFlow 实例**（各基地不同 IP），这个文件夹只是让
"自己起一套"这件事变得方便，不改变现有生产环境接的仍是别处 RAGFlow 的事实。

两套栈虽然各自带 MySQL/Redis/MinIO，但数据完全独立。**不要**尝试让 RAGFlow 复用主项目的
minio/redis：官方栈按自己那套配好的，省这点内存不值得引入耦合和升级风险。

## 新机器同机部署（主项目 + RAGFlow）检查清单

按顺序过一遍。第 1~3 条 `./setup.sh check` 会自动检查：

1. **Docker + Docker Compose v2**（两套栈共用同一个 Docker daemon，互不干扰）。
2. **内核参数 `vm.max_map_count >= 262144`**——Elasticsearch 硬性要求，不设 RAGFlow
   起不来（首启失败的头号原因）：

   ```bash
   sudo sysctl -w vm.max_map_count=262144                                   # 立即生效
   echo 'vm.max_map_count=262144' | sudo tee -a /etc/sysctl.conf && sudo sysctl -p  # 持久化
   ```

3. **端口冲突**——RAGFlow 官方默认往宿主机映射的端口 vs 主项目占用对照：

   | 宿主机端口 | RAGFlow 侧 | 主项目侧 | 处理 |
   | --- | --- | --- | --- |
   | 9000 / 9001 | MinIO（`MINIO_PORT` / `MINIO_CONSOLE_PORT`） | `minio` 服务恰好也是 9000/9001 | **必撞**：改 `ragflow-src/docker/.env`（如 19000/19001） |
   | 6379 | Redis（`REDIS_PORT`） | 主 `redis` 是 16379；`knb-redis`（legacy profile）才占 6379 | 通常不撞；启 legacy 时改一边 |
   | 80 / 443 | Web UI（官方 compose 硬编码） | 主应用是 9300，不撞 | 服务器 80 被别的服务占时要改官方 compose |
   | 9380 | API（`SVR_HTTP_PORT`） | 无 | 不撞 |
   | 5455 / 1200 | MySQL / Elasticsearch | 无 | 不撞 |

4. **资源**：RAGFlow 官方建议单独就要 ≥4 核 / 16GB 内存 / 50GB 磁盘；主项目 7 个服务
   + TimescaleDB（限 4G）叠加在同一台机器时按此往上加，别按主项目单独的量估。
5. **主项目 `.env` 的 `RAGFLOW_BASE_URL` 写宿主机内网 IP**，如 `http://10.x.x.x:9380`。
   不能写 `localhost`——backend 在容器里，localhost 指容器自己（跟 `POSTGRES_HOST`
   是同一个坑，见 `deploy/docker/.env.example` 注释）。
6. 启动顺序无所谓：主项目对 RAGFlow 没有 compose 启动依赖，运行时才调 API，
   哪套先起都行。

## 用法

> 同机部署主项目 + RAGFlow 推荐直接用上层的 `bash ../deploy_all.sh install`：
> 它会调本脚本并自动做端口消歧、校正主项目 `RAGFLOW_BASE_URL`、启动后做链路自检。
> 本脚本单独用于只管 RAGFlow 生命周期的场景（升级、离线打包、单独重启等）。

```bash
cd ragflow
chmod +x setup.sh     # 从 Windows 开发机提交的，可执行位没带过来，先加一次
./setup.sh check       # 只做环境检查（内核参数、端口），不启动
./setup.sh install     # 首次：clone 官方仓库 + 环境检查 + 启动
./setup.sh up          # 之后启动
./setup.sh down        # 停止（数据卷保留；别自己加 -v，会删光数据）
./setup.sh restart
./setup.sh logs
./setup.sh status
RAGFLOW_TAG=v0.xx.x ./setup.sh upgrade   # 升级版本（数据保留），见下文「第二次部署」
```

## 离线部署（服务器无外网）

服务器连不上 github/docker hub 时（各基地服务器常态），跟主项目 `build.bat` 离线打包
同一个思路：

```bash
# ① 在一台有外网的机器上（自动 clone + pull 全套镜像 + docker save）
./setup.sh save-images        # 产出 ragflow-images.tar（约 10+ GB，注意磁盘）

# ② 把整个 deploy/ragflow/（含 ragflow-src/ 源码目录）+ ragflow-images.tar 拷到服务器

# ③ 服务器上
./setup.sh load-images
./setup.sh up
```

## 部署完成后（新实例配置回填）

新实例是空的，**旧实例的 API key / 数据集 / 助手 ID 一律不通用**，按顺序做：

1. `./setup.sh status` 确认容器全部 healthy；浏览器打开 `http://<部署机IP>`
   （Web UI 默认端口 80），注册管理员账号。
2. **配模型供应商**：在 RAGFlow 设置里把通义千问（DashScope）的 API key 配进去。
   主项目默认用 `text-embedding-v4`（embedding）+ `qwen-plus`（chat），对应 env
   `RAGFLOW_EMBEDDING_MODEL` / `RAGFLOW_MODEL`；要换模型时 RAGFlow 侧和主项目 env
   两边一起改。
3. **生成 API key**（用户设置的 API 页）→ 回填 `RAGFLOW_API_KEY`。
4. **建知识库（数据集）** → 回填 `RAGFLOW_DATASET_ID`。文档重新上传解析，或直接用
   系统"知识库管理"页的**发布到 RAGFlow** 重推（推荐——PG 侧的文档映射会一起建好；
   若是从旧实例迁移，PG 里存的旧 document/dataset id 已失效，必须重新发布刷新）。
5. **建两个聊天助手** → 回填 `RAGFLOW_DOC_ASSISTANT_ID`（设备文档助手：维修建议
   工单评分 + 参数报警诊断共用）、`RAGFLOW_HISTORY_ASSISTANT_ID`（维修历史助手：
   维修建议用）。不配则这两块功能拿不到知识库结果。
6. 改完主项目 `deploy/docker/.env` 后重启吃这些变量的容器：
   `docker restart industrial-ai repair-suggestion knb-celery-worker`。

回填变量总表（都在主项目 `deploy/docker/.env`，模板见 `.env.example`）：

| 变量 | 从哪拿 | 谁在用 |
| --- | --- | --- |
| `RAGFLOW_BASE_URL` | `http://<宿主机IP>:9380` | 所有 RAGFlow 相关模块 |
| `RAGFLOW_API_KEY` | RAGFlow 网页后台生成 | 同上 |
| `RAGFLOW_DATASET_ID` | 新建数据集的 ID | 知识库问答 / 报告生成 |
| `RAGFLOW_DOC_ASSISTANT_ID` | 新建"设备文档"助手的 ID | 维修建议 + 参数报警诊断 |
| `RAGFLOW_HISTORY_ASSISTANT_ID` | 新建"维修历史"助手的 ID | 维修建议 |
| `RAGFLOW_EMBEDDING_MODEL` / `RAGFLOW_MODEL` | 与 RAGFlow 里配好的模型对应 | 知识库同步 / 问答 |

## 第二次部署（升级 / 重装 / 再来一套）

上面的清单是"全新机器第一次装"的口径。第二次碰这台机器时按情形对号入座：

**情形 A：重复执行 install / up（配置没变，想确认服务在跑）**

幂等，直接跑，安全。RAGFlow 已在运行时 `check` 会报端口被占用——占用者就是它自己，
按提示忽略即可；`install` 检测到 `ragflow-src/` 已存在会跳过 clone，不会覆盖你改过的配置。

**情形 B：升级 RAGFlow 版本（数据要保留）——最常见的"第二次部署"**

```bash
RAGFLOW_TAG=v0.xx.x ./setup.sh upgrade
```

脚本自动做三步：停服务（不删卷）→ 旧 `ragflow-src/` 改名备份（`ragflow-src.old-<时间戳>`，
不删除）→ clone 新版本。然后**手动两步**（脚本最后会打印提示）：

1. 对照备份目录，把你改过的 `docker/.env`（比如为避开主项目改掉的 MinIO 端口）搬到
   新目录的 .env 里——**不要整个文件覆盖**，新版本 .env 可能有新增键：
   `diff ragflow-src.old-*/docker/.env ragflow-src/docker/.env`
2. `./setup.sh up`

数据都在 docker named volume 里，换源码目录不动它：API key、数据集、助手 ID、已解析
文档全部保留，**主项目 `.env` 什么都不用改，回填流程不用重走**。确认新版本正常后再删
备份目录。注意：升级跨度大时先看官方 release notes 有没有数据迁移/不兼容说明；
离线环境要先在有网机器上对新版本跑一次 `save-images` 换新镜像 tar。

**情形 C：装坏了想清干净重来（数据不要了）**

这是唯一该用 `-v` 的时刻，删卷不可逆，想清楚再执行：

```bash
cd ragflow-src/docker && docker compose down -v   # 删容器 + 全部数据卷
```

然后重新 `./setup.sh install`。因为是全新实例，**上面「部署完成后」的回填流程要完整
重走一遍**：API key/数据集/助手 ID 全变了，主项目 `.env` 重新回填，知识库文档重新
发布（PG 里存的旧 document/dataset id 已失效）。

**情形 D：另一台机器再装一套（比如另一个基地）**

重走「新机器同机部署检查清单」。每套 RAGFlow 实例的 key/ID 相互独立，回填到对应
基地自己的 `deploy/docker/.env`（`.env.prod.*`）里，互不影响。

## 版本

`setup.sh` 里 `REPO_TAG` 固定了一个版本号，部署前建议去
<https://github.com/infiniflow/ragflow/releases> 确认一下是否要换成更新的稳定版
（可以用 `RAGFLOW_TAG=v0.xx.x ./setup.sh install` 覆盖，不用改脚本本身）。
注意不同版本的 `ragflow-src/docker/.env` 端口变量名/默认值可能有出入，
`./setup.sh check` 读的是 clone 下来那份 .env 的实际值。

## 已知限制（本地开发机验证情况）

这套脚本在本地开发机（企业代理环境）没能跑通完整验证——`git clone`/`docker pull`
都需要真的联网，本地这台机器的网络条件连不上（详见同分支 TimescaleDB 那部分踩过
的坑）。脚本逻辑本身是按 RAGFlow 官方标准部署方式写的，**实际服务器上部署时如果
遇到跟这里描述不一致的地方（比如 compose 文件路径、默认端口变了），请反馈，
再回来改这个脚本**。
