#!/usr/bin/env bash
# 配置/结果类数据备份 —— 默认【不备份传感器时序数据】。
#
# 为什么排除传感器数据：device_alarm_info / device_energy_info 是 MQTT 持续写入的
# 原始点位表，体积占绝大多数且可再生（设备还在上报），备份它们既占空间又没什么价值。
# 但库里还有一批小而金贵、丢了要人工重建的表 —— 参数画像、筛选/脉搏设定、阶段配置、
# 知识库、AI 分析报告等，这些必须留备份，所以本脚本改成"排除大表、备其余"。
#
# 用法：
#   ./backup.sh                    # 只备份配置/结果表（推荐，体积很小）
#   INCLUDE_SENSOR_DATA=1 ./backup.sh   # 连传感器原始数据一起备（体积巨大，一般不用）
#   COS_BUCKET=xxx ./backup.sh     # 备份后再传一份到 COS（需先装并配置 coscli）
#
# 建议 crontab（每天 2:30 跑一次，日志留档）：
#   30 2 * * * /opt/industrial-ai/deploy/docker/scripts/backup.sh >> /data/industrial-ai/logs/backup.log 2>&1
#
# 说明：容器卷/绑定挂载只能防"删容器丢数据"，防不了误删库、盘故障、误操作，
# 所以离机备份是必须的另一层。

set -euo pipefail

APP_DATA_ROOT="${APP_DATA_ROOT:-/data/industrial-ai}"
BACKUP_DIR="${APP_DATA_ROOT}/backup"
KEEP_DAYS="${KEEP_DAYS:-14}"
PG_CONTAINER="${PG_CONTAINER:-postgresql}"
ENV_FILE="${ENV_FILE:-${APP_DATA_ROOT}/config/.env}"

ts="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# 从配置文件读库名/用户（不把口令打到命令行，用容器内 peer 认证）
PG_DB="$(grep -E '^PG_DB=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
PG_USER="$(grep -E '^PG_USER=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
PG_DB="${PG_DB:-knowledge_base}"
PG_USER="${PG_USER:-zxzz}"

if ! docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER"; then
  echo "[$(date '+%F %T')] 跳过 PG 备份：容器 $PG_CONTAINER 未运行（可能连的是外部数据库）"
else
  out="${BACKUP_DIR}/pg_${PG_DB}_${ts}.dump"
  # 传感器原始表：默认只备份结构不备份数据（--exclude-table-data），
  # 恢复后表还在、策略还在，只是历史点位为空，设备继续上报就会重新填充。
  excl=()
  if [ -z "${INCLUDE_SENSOR_DATA:-}" ]; then
    for t in device_alarm_info device_energy_info \
             dev_device_param_detail_record dev_device_status_record; do
      excl+=(--exclude-table-data="$t")
    done
    echo "[$(date '+%F %T')] pg_dump（排除传感器时序数据）-> $out"
  else
    echo "[$(date '+%F %T')] pg_dump（含传感器数据，体积可能很大）-> $out"
  fi
  # -Fc 自定义格式：体积小、支持 pg_restore 选择性恢复
  docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" -Fc "${excl[@]}" > "$out"
  # 落盘后校验：空文件或过小说明导出失败，立即报错，避免留下"看起来有备份"的假象
  if [ ! -s "$out" ] || [ "$(stat -c%s "$out")" -lt 1024 ]; then
    echo "[$(date '+%F %T')] 错误：备份文件异常（$(stat -c%s "$out" 2>/dev/null || echo 0) 字节）" >&2
    exit 1
  fi
  echo "[$(date '+%F %T')] 完成，大小 $(du -h "$out" | cut -f1)"
fi

# MinIO（知识库文档原件）：默认不备，需要时 BACKUP_MINIO=1 开启
if [ -n "${BACKUP_MINIO:-}" ] && docker volume inspect industrial_minio >/dev/null 2>&1; then
  out="${BACKUP_DIR}/minio_${ts}.tar.gz"
  echo "[$(date '+%F %T')] 打包 MinIO -> $out"
  docker run --rm -v industrial_minio:/data:ro -v "$BACKUP_DIR":/backup alpine \
    tar czf "/backup/$(basename "$out")" -C /data .
fi

# 清理过期备份
find "$BACKUP_DIR" -name 'pg_*.dump' -mtime "+${KEEP_DAYS}" -delete 2>/dev/null || true
find "$BACKUP_DIR" -name 'minio_*.tar.gz' -mtime "+${KEEP_DAYS}" -delete 2>/dev/null || true

# 可选：上传 COS（异地留一份，防整机/整盘丢失）
if [ -n "${COS_BUCKET:-}" ]; then
  if command -v coscli >/dev/null 2>&1; then
    echo "[$(date '+%F %T')] 上传 COS: $COS_BUCKET"
    coscli sync "$BACKUP_DIR" "cos://${COS_BUCKET}/industrial-ai-backup/" --routines 4
  else
    echo "[$(date '+%F %T')] 警告：设了 COS_BUCKET 但没装 coscli，跳过上传" >&2
  fi
fi

echo "[$(date '+%F %T')] 备份结束。当前备份文件："
ls -lh "$BACKUP_DIR" | tail -5
