# 04. 统一 PostgreSQL 到 TimescaleDB 容器

## 需求概述

把项目里分散的两套 PostgreSQL（业务时序外部主机 `10.1.2.227` + docker-compose 内的 KNB `postgres:15`）合并到 docker 内的单个 `timescale/timescaledb:2.19.1-pg14` 容器；同时把 `device_mqtt_etl`（systemd 跑）改为独立 docker 容器集成进 docker-compose。

> 详细技术设计见：[`docs/superpowers/specs/2026-07-02-unified-timescaledb-design.md`](../superpowers/specs/2026-07-02-unified-timescaledb-design.md)

## 范围

| ✅ 在范围内 | ❌ 不在范围 |
|---|---|
| 业务时序 PG（10.1.2.227）→ 迁到 timescaledb 容器 | agentic_qa（保持 SQLite + MySQL + Chroma + Neo4j） |
| KNB PG（docker-compose 内 `postgresql` 服务）→ 与业务时序合并 | RAGFlow、MinIO、Redis 等其他基础设施 |
| `device_mqtt_etl` systemd → 改为 docker 容器 | 新增功能开发 |
| 配置统一用 `POSTGRES_*`，删除 `PG_*` / `KNB_PG_*` | — |

## 已确认的关键决策

| 决策点 | 选项 |
|---|---|
| agentic_qa 范围 | ❌ 排除 |
| KNB 处理 | ✅ 完全合并到 timescaledb |
| mqtt-etl 部署形态 | ✅ 独立 docker 容器 |
| 代码结构 | ✅ `backend/services/device_mqtt_etl/` |
| 迁移策略 | ✅ 一次性切（4~6 小时维护窗口） |
| 配置统一 | ✅ 仅保留 `POSTGRES_*`，删除 `PG_*` / `KNB_PG_*` |
| schema 隔离 | ✅ 全部放 `public` |
| 用户通知 | ❌ 不需要（开发版，无实际用户） |

## 任务清单

### 准备阶段

- [ ] 1.1 在新机器（部署目标）拉取代码
- [ ] 1.2 创建新的 `docker/.env`：填入 `POSTGRES_HOST=timescaledb` / `POSTGRES_PASSWORD=<新强密码>` / `MQTT_*` 等
- [ ] 1.3 确认 `MQTT_BROKER` 外网地址、用户名密码可用
- [ ] 1.4 准备 `/tmp/migration_backup/` 备份目录（容量预留 50G+）

### 代码改造

- [ ] 2.1 修改 `docker/docker-compose.yml`：
  - [ ] 2.1.1 新增 `timescaledb` 服务（镜像 `timescale/timescaledb:2.19.1-pg14`，端口 `15433:5432`，volume `tsdata`）
  - [ ] 2.1.2 新增 `mqtt-etl` 服务（独立构建）
  - [ ] 2.1.3 删除 `postgresql` 服务（原 KNB 用）
  - [ ] 2.1.4 删除 `knb-postgresql` legacy alias
  - [ ] 2.1.5 声明新 volumes：`tsdata`、`mqtt_etl_dead_letter`
- [ ] 2.2 新增 `docker/mqtt-etl/Dockerfile`
- [ ] 2.3 新增 `docker/scripts/timescale_init/01-extensions.sql`
- [ ] 2.4 把 `D:\Work\device_mqtt_etl` 代码平移到 `backend/services/device_mqtt_etl/`：
  - [ ] 2.4.1 `main.py` — 改 DB 连接读 `POSTGRES_*` env
  - [ ] 2.4.2 `config.py` — 改用环境变量
  - [ ] 2.4.3 `database.py` — DB_HOST 默认 `timescaledb`
  - [ ] 2.4.4 保留死信、缓冲、MQTT 重连等逻辑
- [ ] 2.5 修改 `backend/core/knowledge_management/config.py`：
  - 删 `database_url` property 中的 `KNB_PG_*` / `PG_*` 兼容读取，统一走 `POSTGRES_*`
- [ ] 2.6 新增 `backend/tools/migrate_unified.py`（一次性数据迁移脚本）

### .env 改动

- [ ] 3.1 新增：`POSTGRES_DB=chaowei_business`
- [ ] 3.2 新增：`MQTT_BROKER` / `MQTT_PORT` / `MQTT_TOPIC` / `MQTT_USER` / `MQTT_PASS` / `MQTT_QOS` / `MQTT_BATCH_SIZE` / `MQTT_BATCH_TIMEOUT`
- [ ] 3.3 修改：`POSTGRES_HOST=timescaledb`
- [ ] 3.4 修改：`POSTGRES_PASSWORD=<新强密码>`（原 `Focus&2025!`）
- [ ] 3.5 清空：`POSTGRES_FALLBACK_HOST`
- [ ] 3.6 删除：`PG_*` 系列
- [ ] 3.7 删除：`KNB_PG_*` 系列

### 数据迁移

- [ ] 4.1 启动新 timescaledb 容器（空库自动 init 扩展）
- [ ] 4.2 启动 chaowei-agent 让 SQLAlchemy 建 KNB 表（30+ 张）
- [ ] 4.3 启动 mqtt-etl 容器验证启动正常（暂无数据写入）
- [ ] 4.4 备份旧库：
  - [ ] 4.4.1 业务时序 schema（`pg_dump --schema-only`）
  - [ ] 4.4.2 业务时序普通表数据（sys_user / system_job_config / device_info / point_info / dev_device_param）
  - [ ] 4.4.3 业务时序 hypertable 数据（device_alarm_info / dev_device_param_detail_record / dev_device_status_record，gzip 压缩）
  - [ ] 4.4.4 KNB 整库（`docker exec postgresql pg_dump`）
  - [ ] 4.4.5 异地再备份一份
- [ ] 4.5 维护窗口：停 systemd mqtt-etl + 停 chaowei-agent
- [ ] 4.6 记录旧库 `device_alarm_info.MAX(point_time)` = T_last
- [ ] 4.7 导入数据到新库：
  - [ ] 4.7.1 KNB schema + data
  - [ ] 4.7.2 业务时序普通表 schema
  - [ ] 4.7.3 业务时序普通表 data
  - [ ] 4.7.4 hypertable 转超表（`create_hypertable()`）
  - [ ] 4.7.5 hypertable data（解压再灌）
  - [ ] 4.7.6 retention policy 重灌（如原库有）

### 切流量

- [ ] 5.1 .env 中 `POSTGRES_HOST` 从 `10.1.2.227` 改为 `timescaledb`
- [ ] 5.2 重启 docker 服务：`docker compose up -d chaowei-agent knb-celery-worker mqtt-etl`
- [ ] 5.3 健康检查：`curl http://localhost:9300/api/health`

### 验收

- [ ] 6.1 V.1 timescaledb 容器 healthy
- [ ] 6.2 V.2 KNB 表数量 >= 30 张
- [ ] 6.3 V.3 KNB 用户/权限行数与旧库一致
- [ ] 6.4 V.4 业务时序普通表行数一致
- [ ] 6.5 V.5 业务时序 hypertable 行数一致 + 是 hypertable
- [ ] 6.6 V.6 chaowei-agent 启动无 ERROR
- [ ] 6.7 V.7 KNB 首页可加载
- [ ] 6.8 V.8 业务时序参数图可查
- [ ] 6.9 V.9 报警查询可查
- [ ] 6.10 V.10 system_job_config 可改
- [ ] 6.11 V.11 mqtt-etl 5 分钟后有新数据落库
- [ ] 6.12 V.12 旧库无新写入（`MAX(point_time)` == T_last）

### 清理（验证通过 1 周后）

- [ ] 7.1 备份归档旧库
- [ ] 7.2 `docker compose down postgresql`（保留 30 天观察）
- [ ] 7.3 `docker volume rm knb_pgdata`
- [ ] 7.4 删除 docker-compose.yml 里 `postgresql` / `knb-postgresql` 服务定义
- [ ] 7.5 `sudo systemctl disable --now device-mqtt-etl`

## 验收标准

迁移完成的标志（**全部满足**）：

1. 全部 12 项验证清单（V.1 ~ V.12）通过
2. 至少稳定运行 1 周无异常
3. 旧 `postgresql` 容器已 `down` 且 `knb_pgdata` volume 已删
4. systemd 的 `device-mqtt-etl.service` 已 disable

## 风险点

| 风险 | 缓解 |
|---|---|
| timescaledb 容器挂了影响所有 PG 服务 | healthcheck + restart policy，保留旧 `postgresql` 容器 30 天可回切 |
| KNB 数据迁移字段不匹配导致 ORM 启动失败 | 5.4 备份可在 30 天内回滚；SQLAlchemy 表结构由代码生成，schema 应一致 |
| hypertable 数据量大（24+ 周数千万行）迁移耗时长 | 分批 `COPY` + gzip 压缩传输；预估 2~6 小时 |
| 业务时序表数据导入期间内存爆 | 用 `psycopg2.cursor.copy_expert` 流式 + 每 50w 行一批 |
| mqtt-etl 容器启动失败数据丢 | systemd 版未 disable，回切；dead_letter 兜底 |
| 旧 `Focus&2025!` 密码有 `&` 特殊字符 | 改用无特殊字符的新强密码 |

## 已知问题

- 暂无（迁移为一次性任务，无持续 bug）

## 相关代码位置

**修改**：
- `docker/docker-compose.yml`
- `docker/.env`
- `backend/core/knowledge_management/config.py`

**新增**：
- `docker/mqtt-etl/Dockerfile`
- `docker/scripts/timescale_init/01-extensions.sql`
- `backend/services/device_mqtt_etl/`（平移自 `D:\Work\device_mqtt_etl`）
- `backend/tools/migrate_unified.py`

**相关代码（保留不动但需关注）**：
- `backend/core/knowledge_management/database.py` — SQLAlchemy engine 入口
- `backend/modules/device_warning/ai_analysis/postgres_loader.py` — 业务时序连接入口
- `backend/modules/device_param/services.py` — 业务时序 services
- `backend/modules/auth/service.py` — `sys_user` 表访问
- `backend/routes/system_jobs.py` → `core/system_job_store` — `system_job_config` 访问

## 状态

⏳ **待实施** —— 设计已确认，待后续排期执行。

## 排期建议

| 阶段 | 工作量 | 备注 |
|---|---|---|
| 准备工作（0.1 ~ 0.8 + 2.1 ~ 2.6 + 3.1 ~ 3.7） | 1.5 ~ 2 人日 | 纯代码改动 |
| 备份 + 迁移窗口（4.1 ~ 4.7） | 0.5 人日 + 4~6 小时停机 | 凌晨执行 |
| 切流量 + 验证（5.1 ~ 6.12） | 0.5 人日 | 立即执行 |
| 清理（7.1 ~ 7.5） | 0.2 人日 | 1 周后 |
| **合计** | **约 3 ~ 4 人日** | 不含 1 周观察期 |