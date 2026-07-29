# 部署与启动脚本总览

仓库里的启动/部署入口较多，按使用场景对号入座：

| 场景 | 入口 | 说明 |
| --- | --- | --- |
| 本地裸跑前后端（不用 Docker） | 根目录 `start.bat` / `start.sh` | 数据库等基础设施需自备（外部服务器或已起的容器） |
| 本地一键全容器（开发自测） | 根目录 `start_docker.bat` | 等价于 compose up -d --build |
| Windows 管理 compose（up/build/down/logs） | `deploy/docker/deploy.bat` | up 复用已有镜像；重新构建用 `deploy.bat build` |
| 宿主机裸跑 backend + 容器只跑基础设施 | `deploy/docker/start.bat` | 混合开发模式，env 取值见 `.env.example` 注释 ② |
| 离线打包镜像（客户服务器无外网） | `deploy/docker/build.bat` | 产出 tar → 服务器 `docker load` → compose up（不加 --build） |
| 服务器上 git 拉代码构建部署（多环境） | `deploy/docker/scripts/deploy.sh <env> update` | env: test/prod/shandong/jiangxi/changxing |
| CI 自动部署（rsync 源码 + 服务器构建） | `.gitlab-ci.yml` → `deploy/remote-deploy.sh` | 见下文 CI 变量配置 |
| 首次部署初始化设备字典（手动，一次性） | `deploy/docker/scripts/sync_device_dict.py` | 见下文「首次部署：同步设备字典表」 |
| 贝特瑞(BTR)设备核对+参数/能耗信息导入（手动，一次性） | `deploy/docker/scripts/sync_btr_device_dict.py` | 见下文「贝特瑞(BTR)现场设备核对 + 参数/能耗信息导入」，跟上面 MySQL 同步互不冲突、都要跑 |
| 服务器同机一键部署 主系统 + RAGFlow | `deploy/deploy_all.sh` | 两套一起起 + 自动校正 RAGFLOW_BASE_URL + 链路自检；`check` 子命令单独复查 |
| 自建 RAGFlow（可选，独立于主 compose） | `deploy/ragflow/setup.sh` | 见下文「同机自建 RAGFlow」及 `deploy/ragflow/README.md` |
| 本机 cntlm 隧道重启（开发辅助） | `backend/restart_tunnel.bat` | 与部署无关，连远程数据库用 |

# 首次部署：同步设备字典表（必做，一次性）

全新环境首次 `compose up` 后，PG 里两张字典表是空的——init-sql 只建结构不带数据：

- `device_info`：参数页设备下拉列表（`GET /api/device-params/devices`），空表则前端选不了设备；
- `dev_device_param`：参数编码 → 中文名/单位/排序，空表则点位只显示英文编码。

这两张表的数据源头在 MySQL 业务库(jxcw)，容器启动成功后手动执行一次同步：

```bash
# 在部署目录（服务器上）执行；industrial-ai 容器需已启动，MySQL 可达
docker cp deploy/docker/scripts/sync_device_dict.py industrial-ai:/tmp/
docker exec industrial-ai python /tmp/sync_device_dict.py
```

说明：

- 默认只收录在 `device_alarm_info`（实时点位采集表）里出现过的设备；若采集还没跑起来
  会提示中止，可等有采集数据后再跑，或加 `--all` 先收录全部有参数定义的设备。
- 幂等（upsert，只增改不删），可重复执行；后续 MySQL 侧新增设备/参数后重跑即可增量同步。
- `--dry-run` 只预览不写库。
- MySQL 连接参数取容器内 `MYSQL_*` 环境变量，未设置时回退 `AQA_MYSQL_*`（`.env` 里已有）；
  PG 用与 backend 相同的 `POSTGRES_*`。
- 历史时序数据（状态记录等）的迁移是另一件事，见 `backend/tools/migrate_mysql_to_timescale.py`。

# 贝特瑞(BTR)现场设备核对 + 参数/能耗信息导入（手动，一次性）

贝特瑞是新接入的客户现场，跟江西现场是完全不同的设备清单/编码，互不影响。这个脚本是
两个数据源的混合：

- **设备清单本身**（哪些设备、叫什么名字）：权威源是 MySQL(jxcw) 业务库（`dev_device_param`
  JOIN `dev_device`，按 `device_no LIKE 'BTR%'` 过滤），跟 `sync_device_dict.py` 读的是
  同一套表。PostgreSQL `device_info` 里现有的数据不当参考——脚本读 MySQL 的贝特瑞设备清单，
  跟 PG 现有的 `device_info` 核对，**只补缺失的**，已存在的行不碰。
- **参数信息 + 能耗信息**（点位编码→中文名、电表→生产设备映射）：MySQL 没有这份颗粒度
  的数据，权威源是现场提供的 `docs/贝特瑞AI设备信息表.xlsx`（本地文件，`*.xlsx` 已
  gitignore）。解析结果固化成脚本内置静态常量，全量 upsert 进 `dev_device_param` 和
  新表 `device_energy_meter`。电表本身不在 MySQL 里，所以电表的 `device_info` 也走
  "缺失补充"这条路，数据源是 Excel。

跟 `sync_device_dict.py`（MySQL jxcw 通用字典同步）是两回事、互不冲突。容器启动、MySQL
可达后执行：

```bash
docker cp deploy/docker/scripts/sync_btr_device_dict.py industrial-ai:/tmp/
docker exec industrial-ai python /tmp/sync_btr_device_dict.py            # 常规
docker exec industrial-ai python /tmp/sync_btr_device_dict.py --dry-run  # 只预览不写库（仍会连 MySQL/PG 读取核对结果）
```

说明：

- 写入内容：`device_info`（补齐 MySQL 有但 PG 缺的生产设备 + 29 台电表）、
  `dev_device_param`（76 台生产设备的工艺点位定义 + 29 台电表的能耗点位定义，2086 条）、
  `device_energy_meter`（电表 → 生产设备映射，新表，29 条）。幂等，可重复执行。
- 脚本会打印 MySQL 与 Excel 设备编码的差集提示；如果 Excel 里的生产设备 MySQL 也没有，
  会额外打警告——这类设备的 `dev_device_param` 照样会写，但因为 `device_info` 补不上，
  设备下拉框里选不到，需要人工确认 MySQL 侧数据是否补全。
- 电表在参数分析页会作为一个独立"设备"出现；`backend/modules/device_param/services.py`
  的 `get_param_data`/`get_param_data_aggregated` 已改为 UNION `device_alarm_info` +
  `device_energy_info`，选中电表设备能看到能耗趋势图。
- 以后新现场大概率还是"MySQL 核对设备清单 + Excel 导入参数/能耗信息"这个节奏，届时可以
  照这个脚本的结构（换掉 Excel 数据常量、调整 device_no 过滤前缀）另开一个同类脚本。
- 前提：mqtt_etl 要实际订阅贝特瑞现场的 MQTT topic（`Gycs/chaowei/btr` /
  `NH/chaowei/btr`，见 xlsx 里的 MQTT 信息）才会有真实数据写入
  `device_alarm_info`/`device_energy_info`——这是服务器 `.env`/部署层面的配置，不在这
  个脚本的范围内；没配置之前，字典和查询都是通的，只是表里没有数据。

# 同机自建 RAGFlow（可选）

知识库问答/维修建议/报警诊断依赖的 RAGFlow，可以用 `deploy/ragflow/setup.sh` 在同一台
服务器上自建（官方栈单独一套 compose，与主项目完全独立，支持离线镜像搬运）。

**推荐入口**：`deploy/deploy_all.sh` 一条命令把两套一起装好——自动改 RAGFlow 侧
MinIO 端口避撞、把主项目 `.env` 的 `RAGFLOW_BASE_URL` 校正为本机 IP、启动后从容器
内部实测链路 + 校验 API key：

```bash
bash deploy/deploy_all.sh install   # 首次部署（幂等，重复执行=up）
bash deploy/deploy_all.sh check     # 只自检不启动不改文件（回填配置后复查用）
bash deploy/deploy_all.sh status    # 两套栈容器状态 + 访问地址
bash deploy/deploy_all.sh down      # 停两套（永远不带 -v，数据保留）
```

常用可选环境变量（完整说明见脚本头部注释）：

```bash
HOST_IP=10.x.x.x                  # 本机对外 IP 探测不对时手动指定
DEPLOY_PROFILES="local-db mqtt"   # 主系统要启用的 compose profile
DEPLOY_BUILD=1                    # 主系统 up 时重新构建（默认复用已 load 镜像）
RAGFLOW_URL_OVERWRITE=1           # RAGFLOW_BASE_URL 指向别的机器时也强制切到本机
```

首次 `install` 后去 RAGFlow 网页完成注册管理员/配模型/生成 API key/建数据集和助手，
回填 `deploy/docker/.env` → `bash deploy/deploy_all.sh up` 重启生效 → `check` 复查闭环。

手动部署时，新机器上主项目 + RAGFlow 两套一起起的三个高频坑：

1. 内核参数 `vm.max_map_count` 需 >= 262144（Elasticsearch 硬性要求，不设 RAGFlow 起不来）；
2. RAGFlow 默认把 MinIO 映射到宿主机 9000/9001，与主项目 `minio` **必撞**，
   要改 RAGFlow 侧 `ragflow-src/docker/.env` 的端口；
3. 主项目 `.env` 的 `RAGFLOW_BASE_URL` 必须写宿主机 IP（backend 在容器里，写 localhost
   连不上），且 API key/数据集/助手 ID 都要在新实例里重建后回填。

`cd deploy/ragflow && ./setup.sh check` 可自动检查前两条；完整清单（含离线部署、
配置回填步骤、二次部署/升级/重装）见 `deploy/ragflow/README.md`。升级版本用
`RAGFLOW_TAG=v0.xx.x ./setup.sh upgrade`（数据卷保留，主项目配置不用动）。

以下为 CI 自动部署（rsync + remote-deploy.sh）方案说明。

# 自动化部署说明

本目录用于 Git 平台 pipeline 自动部署到 Linux 服务器。当前方案是：

1. Pipeline 通过 SSH 连接服务器。
2. 用 `rsync` 将当前提交的代码同步到服务器目录。
3. 在服务器执行 `deploy/remote-deploy.sh`。
4. 脚本用 Docker Compose 构建镜像并重启 `industrial-ai` 容器。

## 服务器准备

服务器需要提前安装：

- Docker
- Docker Compose v2，或旧版 `docker-compose`
- curl

首次部署前创建目录，例如：

```bash
sudo mkdir -p /opt/industrial-ai
sudo chown -R "$USER:$USER" /opt/industrial-ai
```

首次 pipeline 会同步代码。部署脚本校验的 env 文件是 `deploy/docker/.env`（compose 变量替换和容器 env_file 都读这一份）；服务器上没有时脚本直接失败，需参考 `deploy/docker/.env.example` 手动创建 `/opt/industrial-ai/deploy/docker/.env` 并填入真实配置后重新运行 pipeline。

## GitLab / git.anosi.cn CI 变量

在项目的 CI/CD Variables 中配置：

| 变量 | 示例 | 说明 |
| --- | --- | --- |
| `DEPLOY_HOST` | `192.168.1.10` | Linux 服务器 IP 或域名 |
| `DEPLOY_USER` | `deploy` | SSH 用户 |
| `DEPLOY_PORT` | `22` | SSH 端口，可不填 |
| `DEPLOY_PATH` | `/opt/industrial-ai` | 服务器部署目录 |
| `DEPLOY_SSH_PRIVATE_KEY` | 私钥内容 | 能登录服务器的 SSH 私钥 |
| `DEPLOY_BRANCH` | `master` | 自动部署分支（默认 master，见 .gitlab-ci.yml） |
| `APP_PORT` | `9300` | 对外访问端口，可不填 |
| `PROVIDER` | `deepseek` | 模型供应商，可不填 |

服务器需要把对应公钥加入 `~/.ssh/authorized_keys`。

## 手动部署

已同步代码后，也可以在服务器手动执行：

```bash
cd /opt/industrial-ai
APP_PORT=9300 PROVIDER=deepseek bash deploy/remote-deploy.sh
```

部署完成后访问：

```text
http://服务器IP:9300
```
