# 本地 TimescaleDB 容器 —— 首次启动初始化脚本

供 `docker compose --profile local-db up -d postgresql`（见 `deploy/docker/docker-compose.yml`）
在**空数据卷**下自动执行，建库建表，免除本地开发对远程 10.1.2.227 隧道的依赖。

## 目录结构

- `00_init_databases.sh` —— 唯一会被 Postgres 官方镜像的
  `docker-entrypoint-initdb.d` 机制自动执行的脚本。补建 `zxzz` 角色（兼容知识库
  模块 `PG_USER` 约定），再依次把下面两份 schema 灌进**同一个** `$POSTGRES_DB`
  （默认 `postgres`）库。
- `schemas/01_schema_postgres.sql` —— 设备参数/job 那部分表结构（24 张）。
- `schemas/02_schema_knowledge_base.sql` —— 知识库那部分表结构（14 张）。

两份表名/索引/约束/序列名互不重叠（已在真实 TimescaleDB 上验证过合并执行无冲突，
共 38 张表），本地开发没必要拆两个 database；远程真实环境仍是 `postgres` +
`knowledge_base` 两个独立 database，这里只是本地简化，不影响应用代码——知识库
模块连接目标库完全由 `PG_DB` env 决定，本地把 `PG_DB` 设成跟 `POSTGRES_DB` 一样
即可（见 `docker/.env.example`）。

`schemas/` 下的两份 `.sql` **不会**被官方镜像自动扫描到（放在子目录，绕开自动执行），
只由 `00_init_databases.sh` 显式调用。

## 内容范围

只有表结构（`CREATE TABLE`/索引/外键/hypertable 转换），**不含历史数据**。
本地跑起来是空表，需要数据可以用 app 自身的 job 触发接口现算填充
（如 `POST /api/device-params/rollup/run`），或手工按需导入。

字典表 `device_info`（参数页设备下拉列表）和 `dev_device_param`（参数中文名/单位）
的数据从 MySQL 同步：`deploy/docker/scripts/sync_device_dict.py`，
用法见 `deploy/README.md`「首次部署：同步设备字典表」。

## 怎么重新生成（远程 schema 变了以后）

本机没有 `pg_dump` 二进制，用的是基于 `information_schema`/`pg_catalog` 内省手搓的
Python 脚本（`dump_schema.py`，本次生成后没有留在仓库里，如需要可以让 Claude 重新写一份，
或改用真的 `pg_dump --schema-only -h 127.0.0.1 -p 15432 -U postgres -d <dbname>`，
如果那台机器上装了 pg_dump 的话，输出格式会更标准，可以直接替换这里的文件）。

生成后建议：在远程建一个临时空库跑一遍新脚本确认无报错，再替换这里的文件（本次改动
就是这样验证的，未影响任何真实数据/角色）。
