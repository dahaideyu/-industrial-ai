#!/usr/bin/env python3
"""
贝特瑞(BTR)现场参数/能耗信息导入 + 设备字典核对：MySQL(jxcw) + docs/贝特瑞AI设备信息表.xlsx → PostgreSQL

背景：现在 PostgreSQL 里已有的数据（device_info 等）一律不当数据参考——不假设里面现有
的内容跟真实情况对齐、可信。真正的权威数据源分两块：

  1. **设备清单本身**（哪些设备存在、叫什么名字）：权威源是 MySQL(jxcw) 业务库，跟
     sync_device_dict.py 读的是同一套表（`dev_device_param` JOIN `dev_device`），
     只是这里按 `device_no LIKE 'BTR%'` 过滤出贝特瑞现场的设备。本脚本读出 MySQL 的
     贝特瑞设备清单，核对 PostgreSQL `device_info` 里已有哪些、缺哪些，**只把缺失的
     补进去**——已经存在的行不做修改（现有数据对不对不由本脚本判断/订正）。
  2. **参数信息 + 能耗信息**（点位编码→中文名、电表→生产设备映射）：MySQL 没有这份
     颗粒度的数据，权威源是现场提供的 `docs/贝特瑞AI设备信息表.xlsx`（工艺参数 sheet +
     能耗参数 sheet）。这部分解析结果固化成脚本内置静态常量（一次性、固定的清单，不
     在容器里现场解析 xlsx），全量 upsert 进 `dev_device_param`（参数信息）和新表
     `device_energy_meter`（能耗信息：电表→生产设备映射）。

electricity 电表本身不在 MySQL 里（MySQL 只管生产设备），所以电表的 device_info 也走
"缺失补充"这条路，数据源是 Excel。

跟江西现场是完全不同的设备清单、不同的 device_id 编码（BTR- 前缀 vs 江西自己的编码），
两边数据不共用、互不影响。

用法（部署服务器上，容器已启动，MySQL 可达）：
  docker cp deploy/docker/scripts/sync_btr_device_dict.py industrial-ai:/tmp/
  docker exec industrial-ai python /tmp/sync_btr_device_dict.py            # 常规
  docker exec industrial-ai python /tmp/sync_btr_device_dict.py --dry-run  # 只预览不写库

连接参数（容器内环境变量）：
  MySQL: MYSQL_* 优先，未设置时回退 AQA_MYSQL_*（与 sync_device_dict.py 一致）
  PG:    POSTGRES_HOST/PORT/DB/USER/PASSWORD（PG_DB 兜底，与 backend 一致）
"""
import os
import sys
import argparse

import pymysql
import pymysql.cursors
import psycopg2
from psycopg2.extras import execute_values


def env_first(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


def connect_mysql():
    cfg = dict(
        host=env_first("MYSQL_HOST", "AQA_MYSQL_HOST", default="CHANGE_ME"),
        port=int(env_first("MYSQL_PORT", "AQA_MYSQL_PORT", default="3306")),
        user=env_first("MYSQL_USER", "AQA_MYSQL_USER", default="zxzz"),
        password=env_first("MYSQL_PASSWORD", "AQA_MYSQL_PASSWORD"),
        database=env_first("MYSQL_DATABASE", "AQA_MYSQL_DATABASE", default="jxcw"),
        charset="utf8mb4",
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor,
    )
    print(f"[MySQL] 连接 {cfg['host']}:{cfg['port']}/{cfg['database']} ...")
    return pymysql.connect(**cfg)


def connect_pg():
    kwargs = dict(
        host=os.getenv("POSTGRES_HOST", "CHANGE_ME"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB") or os.getenv("PG_DB") or "postgres",
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
        connect_timeout=int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "10")),
    )
    sslmode = os.getenv("POSTGRES_SSLMODE")
    if sslmode:
        kwargs["sslmode"] = sslmode
    print(f"[PG] 连接 {kwargs['host']}:{kwargs['port']}/{kwargs['dbname']} ...")
    return psycopg2.connect(**kwargs)


# ────────────────────────── 静态数据（来自 docs/贝特瑞AI设备信息表.xlsx）──────────────────────────
# 只用于「参数信息 + 能耗信息」这部分（dev_device_param / device_energy_meter）以及电表
# 自身的 device_info 补充；76 台生产设备的 device_id/device_type 仍需要在这里列出，因为
# 要靠它把每台设备归到球磨机/合膏机/固化室，从而知道该套哪套工艺点位定义。

# 工艺参数 sheet「设备信息」：(device_id, device_name, device_type)
# device_name 仅供本脚本内部识别 device_type 用，不写入 device_info
# （device_info 的生产设备数据一律以 MySQL 为准，见下面「设备清单核对」）。
PROCESS_DEVICES = [
    ("BTR-QSDLQM-01-001", "1#球磨机", "球磨机"),
    ("BTR-QSDLQM-01-007", "2#球磨机", "球磨机"),
    ("BTR-QSDLQM-01-013", "3#球磨机", "球磨机"),
    ("BTR-QSDLQM-01-019", "4#球磨机", "球磨机"),
    ("BTR-QSDLQM-01-025", "5#球磨机", "球磨机"),
    ("BTR-QSDLQM-02-001", "6#球磨机", "球磨机"),
    ("BTR-QSDLQM-02-007", "7#球磨机", "球磨机"),
    ("BTR-QSDLQM-02-013", "8#球磨机", "球磨机"),
    ("BTR-QSDLQM-02-019", "9#球磨机", "球磨机"),
    ("BTR-QSDLQM-02-025", "10#球磨机", "球磨机"),
    ("BTR-QSDLQM-02-031", "11#球磨机", "球磨机"),
    ("BTR-QSDLQM-02-037", "12#球磨机", "球磨机"),
    ("BTR-QSDLQM-02-043", "13#球磨机", "球磨机"),
    ("BTR-QSDLQM-02-049", "14#球磨机", "球磨机"),
    ("BTR-QSDLQM-02-053", "15#球磨机", "球磨机"),
    ("BTR-QSDLHG-01-001", "负1#真空合膏机", "合膏机"),
    ("BTR-QSDLHG-01-002", "负2#真空合膏机", "合膏机"),
    ("BTR-QSDLHG-01-004", "负3#真空合膏机", "合膏机"),
    ("BTR-QSDLHG-01-005", "负4#真空合膏机", "合膏机"),
    ("BTR-QSDLHG-01-007", "负5#真空合膏机", "合膏机"),
    ("BTR-QSDLHG-01-008", "负6#真空合膏机", "合膏机"),
    ("BTR-QSDLHG02-001", "正1#真空合膏机", "合膏机"),
    ("BTR-QSDLHG02-002", "正2#真空合膏机", "合膏机"),
    ("BTR-QSDLHG02-004", "正3#真空合膏机", "合膏机"),
    ("BTR-QSDLHG02-005", "正4#真空合膏机", "合膏机"),
    ("BTR-QSDLGH-02-001", "正板1#固化室", "固化室"),
    ("BTR-QSDLGH-02-002", "正板2#固化室", "固化室"),
    ("BTR-QSDLGH-02-003", "正板3#固化室", "固化室"),
    ("BTR-QSDLGH-02-004", "正板4#固化室", "固化室"),
    ("BTR-QSDLGH-02-005", "正板5#固化室", "固化室"),
    ("BTR-QSDLGH-02-006", "正板6#固化室", "固化室"),
    ("BTR-QSDLGH-02-007", "正板7#固化室", "固化室"),
    ("BTR-QSDLGH-02-008", "正板8#固化室", "固化室"),
    ("BTR-QSDLGH-02-009", "正板9#固化室", "固化室"),
    ("BTR-QSDLGH-02-010", "正板10#固化室", "固化室"),
    ("BTR-QSDLGH-02-011", "正板11#固化室", "固化室"),
    ("BTR-QSDLGH-02-012", "正板12#固化室", "固化室"),
    ("BTR-QSDLGH-02-013", "正板13#固化室", "固化室"),
    ("BTR-QSDLGH-02-014", "正板14#固化室", "固化室"),
    ("BTR-QSDLGH-02-015", "正板15#固化室", "固化室"),
    ("BTR-QSDLGH-02-016", "正板16#固化室", "固化室"),
    ("BTR-QSDLGH-02-017", "正板17#固化室", "固化室"),
    ("BTR-QSDLGH-02-018", "正板18#固化室", "固化室"),
    ("BTR-QSDLGH-02-019", "正板19#固化室", "固化室"),
    ("BTR-QSDLGH-02-020", "正板20#固化室", "固化室"),
    ("BTR-QSDLGH-02-021", "正板21#固化室", "固化室"),
    ("BTR-QSDLGH-02-022", "正板22#固化室", "固化室"),
    ("BTR-QSDLGH-02-023", "正板23#固化室", "固化室"),
    ("BTR-QSDLGH-02-024", "正板24#固化室", "固化室"),
    ("BTR-QSDLGH-02-025", "正板25#固化室", "固化室"),
    ("BTR-QSDLGH-02-026", "正板26#固化室", "固化室"),
    ("BTR-QSDLGH-02-027", "正板27#固化室", "固化室"),
    ("BTR-QSDLGH-02-028", "正板28#固化室", "固化室"),
    ("BTR-QSDLGH-02-029", "正板29#固化室", "固化室"),
    ("BTR-QSDLGH-01-001", "负板1#固化室", "固化室"),
    ("BTR-QSDLGH-01-002", "负板2#固化室", "固化室"),
    ("BTR-QSDLGH-01-003", "负板3#固化室", "固化室"),
    ("BTR-QSDLGH-01-004", "负板4#固化室", "固化室"),
    ("BTR-QSDLGH-01-005", "负板5#固化室", "固化室"),
    ("BTR-QSDLGH-01-006", "负板6#固化室", "固化室"),
    ("BTR-QSDLGH-01-007", "负板7#固化室", "固化室"),
    ("BTR-QSDLGH-01-008", "负板8#固化室", "固化室"),
    ("BTR-QSDLGH-01-009", "负板9#固化室", "固化室"),
    ("BTR-QSDLGH-01-010", "负板10#固化室", "固化室"),
    ("BTR-QSDLGH-01-011", "负板11#固化室", "固化室"),
    ("BTR-QSDLGH-01-012", "负板12#固化室", "固化室"),
    ("BTR-QSDLGH-01-013", "负板13#固化室", "固化室"),
    ("BTR-QSDLGH-01-014", "负板14#固化室", "固化室"),
    ("BTR-QSDLGH-01-015", "负板15#固化室", "固化室"),
    ("BTR-QSDLGH-01-016", "负板16#固化室", "固化室"),
    ("BTR-QSDLGH-01-017", "负板17#固化室", "固化室"),
    ("BTR-QSDLGH-01-018", "负板18#固化室", "固化室"),
    ("BTR-QSDLGH-01-019", "负板19#固化室", "固化室"),
    ("BTR-QSDLGH-01-020", "负板20#固化室", "固化室"),
    ("BTR-QSDLGH-01-021", "负板21#固化室", "固化室"),
    ("BTR-QSDLGH-01-022", "负板22#固化室", "固化室"),
]

# 工艺参数 sheet 三套「点位信息」：device_type -> [(point_code, point_name), ...]
POINT_SETS = {
    "球磨机": [
        ("Tec_AbsFilterDPre", "过滤器压差"),
        ("Tec_BagDPre", "布袋压差"),
        ("Tec_FrontBearingTemp", "前轴承温度"),
        ("Tec_FrontSecTemp", "前段温度"),
        ("Tec_LeadPelWT", "铅粒仓重量"),
        ("Tec_LeadPowTemp", "铅粉温度"),
        ("Tec_MidSecTemp", "中段温度"),
        ("Tec_NegDamPre", "负风门压差"),
        ("Tec_PosDamPre", "正风门压差"),
        ("Tec_Power", "功率"),
        ("Tec_RearBearingTemp", "后轴承温度"),
        ("Tec_RearSecTemp", "后段温度"),
    ],
    "合膏机": [
        ("Tec_AcidRealWT", "酸实时重量"),
        ("Tec_AcidRes", "酸残余量"),
        ("Tec_AcidWT", "酸用量"),
        ("Tec_End", "合膏结束"),
        ("Tec_LeadRealWT", "铅实时重量"),
        ("Tec_LeadRes", "铅残余量"),
        ("Tec_LeadWT", "铅用量"),
        ("Tec_MixMaxTemp", "合膏最高温度"),
        ("Tec_MixTemp", "合膏温度"),
        ("Tec_Stage", "合膏阶段"),
        ("Tec_VacDegree", "合膏真空度"),
        ("Tec_WaterRealWT", "水实时重量"),
        ("Tec_WaterRes", "水残余量"),
        ("Tec_WaterWT", "水用量"),
    ],
    "固化室": [
        ("Tec_DQD_DH", "当前段号"),
        ("Tec_DQD_Hour", "当前运行时间时"),
        ("Tec_DQD_Min", "当前运行时间分"),
        ("Tec_DQD_Sec", "当前运行时间秒"),
        ("Tec_DQG_TH", "当前工艺套数"),
        ("Tec_DQR_ZH", "当前运行组号"),
        ("Tec_Fan", "排湿风机运行"),
        ("Tec_Inverter_speed", "循环风机转速"),
        ("Tec_RRD_DH", "实际运行总阶段数"),
        ("Tec_Set_Hour", "阶段设定时间时"),
        ("Tec_Set_Hum", "设定湿度"),
        ("Tec_Set_Min", "阶段设定时间分"),
        ("Tec_Set_tep", "设定温度"),
        ("Tec_Time_Hum", "实时湿度"),
        ("Tec_Time_Tem", "实时温度"),
        ("Tec_Total_Hour", "总运行时间时"),
        ("Tec_Total_Min", "总运行时间分"),
    ],
}

# 能耗参数 sheet「电表信息和生产设备对应关系」：(meter_device_id, meter_name, production_device_id)
ENERGY_METERS = [
    ("c3w9ot7k_EMQSDLQM-01-001", "1#球磨机电表", "BTR-QSDLQM-01-001"),
    ("c3w9ot7k_EMQSDLQM-01-007", "2#球磨机电表", "BTR-QSDLQM-01-007"),
    ("c3w9ot7k_EMQSDLQM-01-013", "3#球磨机电表", "BTR-QSDLQM-01-013"),
    ("c3w9ot7k_EMQSDLQM-01-019", "4#球磨机电表", "BTR-QSDLQM-01-019"),
    ("c3w9ot7k_EMQSDLQM-01-025", "5#球磨机电表", "BTR-QSDLQM-01-025"),
    ("c3w9ot7k_EMQSDLQM-02-001", "6#球磨机电表", "BTR-QSDLQM-02-001"),
    ("c3w9ot7k_EMQSDLQM-02-007", "7#球磨机电表", "BTR-QSDLQM-02-007"),
    ("c3w9ot7k_EMQSDLQM-02-013", "8#球磨机电表", "BTR-QSDLQM-02-013"),
    ("c3w9ot7k_EMQSDLQM-02-019", "9#球磨机电表", "BTR-QSDLQM-02-019"),
    ("c3w9ot7k_EMQSDLQM-02-025", "10#球磨机电表", "BTR-QSDLQM-02-025"),
    ("c3w9ot7k_EMQSDLQM-02-043", "13#球磨机电表", "BTR-QSDLQM-02-043"),
    ("wvhdsx86_EMQSDLQM-02-031", "11#球磨机电表", "BTR-QSDLQM-02-031"),
    ("wvhdsx86_EMQSDLQM-02-037", "12#球磨机电表", "BTR-QSDLQM-02-037"),
    ("wvhdsx86_EMQSDLQM-02-049", "14#球磨机电表", "BTR-QSDLQM-02-049"),
    ("wvhdsx86_EMQSDLQM-02-053", "15#球磨机电表", "BTR-QSDLQM-02-053"),
    ("ywjui12w_EMQSDLHG-01-001", "负1#真空合膏机电表", "BTR-QSDLHG-01-001"),
    ("ywjui12w_EMQSDLHG-01-002", "负2#真空合膏机电表", "BTR-QSDLHG-01-002"),
    ("ywjui12w_EMQSDLHG-01-004", "负3#真空合膏机电表", "BTR-QSDLHG-01-004"),
    ("ywjui12w_EMQSDLHG-01-005", "负4#真空合膏机电表", "BTR-QSDLHG-01-005"),
    ("ywjui12w_EMQSDLHG-01-007", "负5#真空合膏机电表", "BTR-QSDLHG-01-007"),
    ("ywjui12w_EMQSDLHG-01-008", "负6#真空合膏机电表", "BTR-QSDLHG-01-008"),
    ("c3w9ot7k_EMQSDLHG02-001", "正1#真空合膏机电表", "BTR-QSDLHG02-001"),
    ("c3w9ot7k_EMQSDLHG02-002", "正2#真空合膏机电表", "BTR-QSDLHG02-002"),
    ("c3w9ot7k_EMQSDLHG02-004", "正3#真空合膏机电表", "BTR-QSDLHG02-004"),
    ("c3w9ot7k_EMQSDLHG02-005", "正4#真空合膏机电表", "BTR-QSDLHG02-005"),
    ("c3w9ot7k_EMQSDLGH-02-001", "正板固化室A区电表", "BTR-QSDLGH-02-001"),
    ("c3w9ot7k_EMQSDLGH-02-002", "正板固化室B区电表", "BTR-QSDLGH-02-002"),
    ("c3w9ot7k_EMQSDLGH-01-001", "负板固化室北区电表", "BTR-QSDLGH-01-001"),
    ("c3w9ot7k_EMQSDLGH-01-002", "负板固化室南区电表", "BTR-QSDLGH-01-002"),
]

# 能耗参数 sheet「能耗参数点位信息」：(point_code, point_name)，31 个点位所有电表共用
ENERGY_POINTS = [
    ("ene_pt", "电压变比"),
    ("ene_ct", "电流变比"),
    ("ene_ua", "A相电压"),
    ("ene_ub", "B相电压"),
    ("ene_uc", "C相电压"),
    ("ene_uab", "AB线电压"),
    ("ene_ubc", "BC线电压"),
    ("ene_uca", "CA线电压"),
    ("ene_ia", "A相电流"),
    ("ene_ib", "B相电流"),
    ("ene_ic", "C相电流"),
    ("ene_pa", "A相有功功率"),
    ("ene_pb", "B相有功功率"),
    ("ene_pc", "C相有功功率"),
    ("ene_ps", "总有功功率"),
    ("ene_qa", "A相无功功率"),
    ("ene_qb", "B相无功功率"),
    ("ene_qc", "C相无功功率"),
    ("ene_qs", "总无功功率"),
    ("ene_sa", "A相视在功率"),
    ("ene_sb", "B相视在功率"),
    ("ene_sc", "C相视在功率"),
    ("ene_ss", "总视在功率"),
    ("ene_pfa", "A相功率因数"),
    ("ene_pfb", "B相功率因数"),
    ("ene_pfc", "C相功率因数"),
    ("ene_pf", "总功率因数"),
    ("ene_fq", "频率"),
    ("ene_eptotal", "组合有功总电能"),
    ("ene_imp", "正向有功电能"),
    ("ene_exp", "反向有功电能"),
]

# dev_device_param.id 是 BIGINT 主键；MySQL 同步的行直接用 MySQL 自增 id，这批数据没有
# MySQL id，从一个足够大的偏移量开始按固定顺序分配，避免和 MySQL 侧 id 撞车。
_DEV_DEVICE_PARAM_ID_BASE = 9_000_000_000


def build_dev_device_param_rows():
    """按 PROCESS_DEVICES/ENERGY_METERS 的固定顺序展开，id 每次运行都一样（幂等 upsert 用）。"""
    rows = []
    next_id = _DEV_DEVICE_PARAM_ID_BASE
    for device_id, _name, device_type in PROCESS_DEVICES:
        for sort_num, (point_code, point_name) in enumerate(POINT_SETS[device_type], start=1):
            rows.append((next_id, device_id, point_code, point_name, None, sort_num))
            next_id += 1
    for meter_device_id, _name, _prod_id in ENERGY_METERS:
        for sort_num, (point_code, point_name) in enumerate(ENERGY_POINTS, start=1):
            rows.append((next_id, meter_device_id, point_code, point_name, None, sort_num))
            next_id += 1
    return rows


# ────────────────────────── 设备清单核对（MySQL → PG device_info，缺失才补）──────────────────────────

def fetch_mysql_btr_devices(my):
    """MySQL(jxcw) `dev_device_param` JOIN `dev_device`，按 device_no LIKE 'BTR%' 过滤出
    贝特瑞现场的生产设备清单。跟 sync_device_dict.py 的 fetch_devices_from_mysql 同一套
    查询逻辑，只是多了 BTR 前缀过滤。返回 [(device_no, device_name, mysql_id), ...]。"""
    sql = """
        SELECT p.device_no, d.name AS device_name, d.id
        FROM (SELECT DISTINCT device_no, device_id FROM dev_device_param
              WHERE device_no LIKE 'BTR%') p
        JOIN dev_device d ON d.id = p.device_id
        WHERE d.del_flag = 0
        ORDER BY d.id
    """
    with my.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    seen, devices = set(), []
    for r in rows:
        if r["device_no"] in seen:
            continue
        seen.add(r["device_no"])
        devices.append((r["device_no"], r["device_name"], r["id"]))
    return devices


def fetch_pg_existing_device_ids(pg):
    with pg.cursor() as cur:
        cur.execute("SELECT device_id FROM device_info")
        return {row[0] for row in cur.fetchall()}


def supplement_device_info(pg, rows):
    """rows: [(device_id, device_name, mysql_id_or_None), ...]，只 INSERT device_info
    里还没有的 device_id，已存在的行不碰（现有数据对不对不由本脚本判断/订正）。"""
    if not rows:
        return
    with pg.cursor() as cur:
        execute_values(
            cur,
            """INSERT INTO device_info (device_id, device_name, id) VALUES %s
               ON CONFLICT (device_id) DO NOTHING""",
            rows,
        )
    pg.commit()


# ────────────────────────── 建表 / upsert（参数信息 + 能耗信息，来自 Excel）──────────────────────────

def ensure_device_energy_info(pg):
    """device_energy_info 是 mqtt_etl 侧的电表能耗原始点位表；DDL 与
    mqtt_etl/database.py._ensure_schema() 保持一致。backend 这边也要能建它，
    否则 mqtt-etl 容器从没起过的环境里，UNION 这张表的查询会报表不存在。"""
    with pg.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_energy_info (
                device_id varchar(255) NOT NULL,
                device_status varchar(255) NULL,
                point_uid int4 NULL,
                point_id varchar(255) NOT NULL,
                point_value numeric(14,4) NULL,
                point_time timestamp NOT NULL,
                upload_cycle int4 NULL,
                south_driver_name varchar(255) NULL,
                "time" timestamp NULL,
                load_time timestamp NULL,
                raw_json jsonb NULL
            )
        """)
    pg.commit()


def ensure_device_energy_meter(pg):
    """电表 → 生产设备 对应关系表（新表，本脚本引入）。"""
    with pg.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_energy_meter (
                meter_device_id VARCHAR(64) PRIMARY KEY,
                production_device_id VARCHAR(64) NOT NULL REFERENCES device_info(device_id)
            )
        """)
    pg.commit()


def upsert_dev_device_param(pg, rows):
    """rows: [(id, device_no, name, description, unit, sort_num), ...]"""
    with pg.cursor() as cur:
        execute_values(
            cur,
            """INSERT INTO dev_device_param (id, device_no, name, description, unit, sort_num)
               VALUES %s
               ON CONFLICT (id) DO UPDATE SET
                   device_no = EXCLUDED.device_no,
                   name = EXCLUDED.name,
                   description = EXCLUDED.description,
                   unit = EXCLUDED.unit,
                   sort_num = EXCLUDED.sort_num""",
            rows,
        )
    pg.commit()


def upsert_device_energy_meter(pg, rows):
    """rows: [(meter_device_id, production_device_id), ...]"""
    with pg.cursor() as cur:
        execute_values(
            cur,
            """INSERT INTO device_energy_meter (meter_device_id, production_device_id) VALUES %s
               ON CONFLICT (meter_device_id) DO UPDATE
               SET production_device_id = EXCLUDED.production_device_id""",
            rows,
        )
    pg.commit()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="贝特瑞(BTR) 设备清单核对(MySQL) + 参数/能耗信息导入(Excel) → PG")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写库")
    args = ap.parse_args()

    my = connect_mysql()
    pg = connect_pg()
    try:
        # ── 第一部分：MySQL 设备清单 → 核对/补充 PG device_info ──
        mysql_devices = fetch_mysql_btr_devices(my)
        existing_ids = fetch_pg_existing_device_ids(pg)

        missing_production = [
            (dno, name, mid) for dno, name, mid in mysql_devices if dno not in existing_ids
        ]
        missing_meters = [
            (m[0], m[1], None) for m in ENERGY_METERS if m[0] not in existing_ids
        ]

        print(f"[MySQL] 读到贝特瑞生产设备 {len(mysql_devices)} 台（device_no LIKE 'BTR%'）")
        print(f"[device_info] PG 现有 {len(existing_ids)} 条；"
              f"缺失待补充：生产设备 {len(missing_production)} 台，电表 {len(missing_meters)} 台")

        excel_ids = {d[0] for d in PROCESS_DEVICES}
        mysql_ids = {d[0] for d in mysql_devices}
        only_in_mysql = mysql_ids - excel_ids
        only_in_excel = excel_ids - mysql_ids
        if only_in_mysql:
            print(f"[提示] MySQL 有但 Excel 没有的设备编码（{len(only_in_mysql)} 个）："
                  f"{sorted(only_in_mysql)}")
        if only_in_excel:
            print(f"[提示] Excel 有但 MySQL 没有的设备编码（{len(only_in_excel)} 个）："
                  f"{sorted(only_in_excel)}")

        # 补完 device_info 之后，仍然可能有 Excel 里的生产设备既不在 MySQL 也不在 PG
        # 现有数据里——这些设备下面还是会写 dev_device_param，但不会出现在设备下拉框里，
        # 提前提醒，不做静默兜底写入（设备清单权威源只认 MySQL，不擅自用 Excel 顶替）。
        will_exist = existing_ids | {r[0] for r in missing_production} | {r[0] for r in missing_meters}
        orphaned = excel_ids - will_exist
        if orphaned:
            print(f"[警告] 以下生产设备在 device_info 里仍然缺失（MySQL 也没有），"
                  f"dev_device_param 会写但设备下拉框选不到，需要人工确认 MySQL 侧数据："
                  f"{sorted(orphaned)}")

        dev_device_param_rows = build_dev_device_param_rows()
        meter_mapping_rows = [(m[0], m[2]) for m in ENERGY_METERS]

        print(f"[预览] dev_device_param（参数信息+能耗点位）：{len(dev_device_param_rows)} 条"
              f"（{len(PROCESS_DEVICES)} 台生产设备 × 工艺点位 + {len(ENERGY_METERS)} 台电表 × 能耗点位）")
        print(f"[预览] device_energy_meter（能耗信息：电表↔生产设备映射）：{len(meter_mapping_rows)} 条")

        if args.dry_run:
            print("[dry-run] 未写库")
            return 0

        # ── 第二部分：写库 ──
        ensure_device_energy_info(pg)
        ensure_device_energy_meter(pg)

        supplement_device_info(pg, missing_production + missing_meters)
        print(f"[device_info] 已补充 {len(missing_production) + len(missing_meters)} 条缺失设备")

        upsert_dev_device_param(pg, dev_device_param_rows)
        print(f"[dev_device_param] 参数信息已 upsert {len(dev_device_param_rows)} 条")

        upsert_device_energy_meter(pg, meter_mapping_rows)
        print(f"[device_energy_meter] 能耗信息已 upsert {len(meter_mapping_rows)} 条")

        print("[完成] 贝特瑞(BTR)设备核对 + 参数/能耗信息导入完成")
        return 0
    finally:
        my.close()
        pg.close()


if __name__ == "__main__":
    sys.exit(main())
