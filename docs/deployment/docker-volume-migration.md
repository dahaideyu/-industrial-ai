# Docker 数据卷迁移（compose 项目名改名后）

> 触发原因：2026-07 把容器/镜像名从 `chaowei-agent` 统一改成了 `industrial-ai`
> （中间短暂用过 `ai-agent`，未实际部署到任何服务器就又改了，历史名里一并列出以防万一）。
> 其中 `scripts/deploy.sh` 的 `PROJECT_NAME`（`-p` 参数）从 `chaowei-${ENV}` 改成了
> `industrial-ai-${ENV}`；`remote-deploy.sh` 的 `COMPOSE_PROJECT_NAME` 同理从
> `chaowei-agent` 改成了 `industrial-ai`。
>
> Docker Compose 对没有显式命名的数据卷，会自动加上 `<项目名>_` 前缀。项目名一变，
> 下次 `docker compose up` 用的就是一批全新前缀的空卷，旧卷不会自动带过去——
> 数据没有被删除，只是"失联"了。本文档只在**服务器上确实已经跑过旧项目名、且卷里有
> 需要保留的数据**时才需要执行；本次改名时确认过现有几个环境卷内还没有需要保留的
> 数据，属于预防性文档，留作以后同类改名 / 换服务器时的操作手册。

## 受影响的数据卷

以下卷在 `deploy/docker/docker-compose.yml` 里没有显式指定名字，卷名由 compose 项目名自动拼出：

| 卷（compose 里的 key） | 用途 | 是否默认随环境启动 |
|---|---|---|
| `minio_data` | MinIO 对象存储，知识库上传/转换后的文件 | 是（`minio` 服务无 profile 限制） |
| `pgdata` | 本地容器化 TimescaleDB 数据 | 否，仅 `--profile local-db` 时才会创建/使用 |
| `knb_minio_data` / `knb_pgdata` | 旧命名兼容（`legacy` profile） | 否，仅 `--profile legacy` 时才会创建/使用 |

生产/测试环境默认连外部数据库（CHANGE_ME），一般不会用到 `local-db`/`legacy` profile，
所以实际最需要关心的是 **`minio_data`**。如果某个环境确实开过 `--profile local-db`
或 `--profile legacy`，把下面的步骤对 `pgdata`/`knb_pgdata`/`knb_minio_data` 各重复一遍即可。

## 第一步：确认要不要迁移

在目标服务器上执行（把 `changxing` 换成实际环境名：test / prod / shandong / jiangxi / changxing / weifu）：

```bash
# 列出所有历史项目名下的卷（chaowei-<env> 是最早的名字，ai-agent-<env> 是中间短暂用过的名字）
docker volume ls --format '{{.Name}}' | grep -E '^(chaowei-|ai-agent-)'

# 看某个卷里实际有没有数据（不为空、不是刚建的空卷）——把命令里的卷名换成上一步实际列出来的
docker run --rm -v chaowei-changxing_minio_data:/data alpine du -sh /data
```

如果 `du` 结果接近 0（只有 MinIO 自己的元数据目录），说明这个环境本来就没积累真实数据，
**不需要迁移**，直接按新项目名部署即可，跳过下面的步骤。

## 第二步：迁移 minio_data

思路：Docker 不支持给卷改名，只能新建一个卷、把旧卷内容整份拷过去。用一次性的
`alpine` 容器做拷贝，全程不需要真正跑起 MinIO/应用容器，风险很低。

```bash
ENV=changxing   # 换成实际环境名
OLD_VOL="chaowei-${ENV}_minio_data"       # 如果第一步查到的是 ai-agent-${ENV}_minio_data，这里换成那个
NEW_VOL="industrial-ai-${ENV}_minio_data"

# 1. 先建好新卷（compose 首次 up 时也会自动建，这里手动建是为了在 up 之前先把数据拷进去）
docker volume create "$NEW_VOL"

# 2. 整份拷贝（保留权限/属主，-a）；用临时容器同时挂载新旧两个卷
docker run --rm \
  -v "${OLD_VOL}:/from:ro" \
  -v "${NEW_VOL}:/to" \
  alpine sh -c "cp -a /from/. /to/"

# 3. 校验：两边文件数量/总大小应该一致
docker run --rm -v "${OLD_VOL}:/data" alpine sh -c "find /data | wc -l; du -sh /data"
docker run --rm -v "${NEW_VOL}:/data" alpine sh -c "find /data | wc -l; du -sh /data"
```

如果环境用的是 `remote-deploy.sh`（通用 pipeline，项目名固定、不带环境后缀），
把上面的 `OLD_VOL`/`NEW_VOL` 换成：

```bash
OLD_VOL="chaowei-agent_minio_data"   # 或 ai-agent_minio_data，看第一步查到哪个
NEW_VOL="industrial-ai_minio_data"
```

## 第三步：正常部署

数据拷完之后，按平时的流程更新代码、启动即可，compose 会直接复用刚才建好的 `$NEW_VOL`：

```bash
cd /opt/chaowei-agent/deploy/docker   # 老服务器目录名未改，见下方说明
./scripts/deploy.sh "$ENV" update
```

启动后打开 MinIO 控制台（`http://服务器:9001`，账号密码见 `.env` 的
`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`），核对 bucket 列表和文件数量与迁移前一致；
或者在业务侧（知识库管理页）随便打开几份旧文档，确认能正常预览/下载。

## 回滚

拷贝用的是 `cp`，旧卷 `$OLD_VOL` 全程没有被修改或删除。如果新环境启动后发现异常，
把 `scripts/deploy.sh` 的 `PROJECT_NAME` 临时改回旧名（`chaowei-${ENV}` 或
`ai-agent-${ENV}`，看之前用的是哪个）重新部署一次，就能用回旧卷、旧数据完好，
不影响排查问题。确认新环境稳定运行一段时间后，再手动清理旧卷：

```bash
docker volume rm "chaowei-${ENV}_minio_data"   # 换成实际的旧卷名
```

## 关于 `/opt/chaowei-agent` 目录名

这几次改名**没有**动服务器上的项目 checkout 目录路径（`deploy/README.md`、
`scripts/deploy.sh` 里的 `/opt/chaowei-agent`），只改了 Docker 容器/镜像/项目名。
目录路径是否要跟着改是完全独立的决定（涉及实际 `mv` 目录、改 crontab/systemd 里
写死的路径等），本文档不涉及，需要时再单独评估。
