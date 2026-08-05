# cython: annotation_typing=False, infer_types=False, language_level=3
"""
PostgreSQL (TimescaleDB) 设备参数数据查询模块
替代原 MySQL 查询，数据已从 MySQL 迁移到 TimescaleDB
"""
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import psycopg2

from core.pg_env import pg_params
from psycopg2.extras import RealDictCursor

try:
    import pymysql
    HAS_PYMYSQL = True
except ImportError:
    HAS_PYMYSQL = False


def _curated_visible_device_ids(conn) -> List[str]:
    """一次性迁移用：按旧版 get_devices() 硬编码的球磨机白名单+每类型3台上限逻辑，
    算出"应该保持可见"的设备清单——只在新增 visible_in_params 列时调用一次，
    保证上线那一刻下拉框跟改造前完全一样。之后新设备/新增可见都在
    "系统管理→设备列表"页里由管理员手动开，不再走这套硬编码。
    """
    PREFERRED_BALL_MILL_CODES = ('BTR-QSDLQM-02-025', 'BTR-QSDLQM-02-031')
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("""
            SELECT di.id, di.device_id AS device_code,
                   CASE
                       WHEN di.device_id LIKE 'BTR-QSDLQM%' THEN '球磨机'
                       WHEN di.device_id LIKE 'BTR-QSDLHG%' THEN '合膏机'
                       WHEN di.device_id LIKE 'BTR-QSDLGH%' THEN '固化室'
                       ELSE '其他'
                   END AS device_type
            FROM device_info di
            WHERE di.device_id LIKE 'BTR-QSDLQM%'
               OR di.device_id LIKE 'BTR-QSDLHG%'
               OR di.device_id LIKE 'BTR-QSDLGH%'
            ORDER BY device_type, di.id
        """)
        devices = [dict(row) for row in cursor.fetchall()]

    type_count: Dict[str, int] = {}
    visible_ids: List[str] = []
    for dev in devices:
        dev_type = dev['device_type']
        if dev_type == '球磨机' and dev['device_code'] not in PREFERRED_BALL_MILL_CODES:
            continue
        if type_count.get(dev_type, 0) < 3:
            visible_ids.append(dev['device_code'])
            type_count[dev_type] = type_count.get(dev_type, 0) + 1
    return visible_ids


def ensure_visible_in_params_column(conn) -> None:
    """device_info 新增 visible_in_params 列(参数分析页下拉框是否显示该设备)，
    幂等——只在列不存在时建列+一次性回填，之后每次调用都只是一次轻量的
    information_schema 查询，不会重复回填、也不会覆盖管理员之后的手动调整。
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT 1 FROM information_schema.columns
                       WHERE table_name='device_info' AND column_name='visible_in_params'""")
        if cur.fetchone() is not None:
            return
        cur.execute("ALTER TABLE device_info ADD COLUMN visible_in_params "
                    "BOOLEAN NOT NULL DEFAULT false")
    visible_ids = _curated_visible_device_ids(conn)
    if visible_ids:
        with conn.cursor() as cur:
            cur.execute("UPDATE device_info SET visible_in_params = true "
                       "WHERE device_id = ANY(%s)", (visible_ids,))
    conn.commit()
    print(f"[device_info] 新增 visible_in_params 列，回填 {len(visible_ids)} 台设备为可见"
          "(保持改造前下拉框一致)")


class TimescaleDB:
    """PostgreSQL (TimescaleDB) 设备参数数据库操作类"""

    # 能耗点位白名单：参数分析/阶段分析/AI诊断只展示这两个能耗指标
    _ENERGY_POINT_WHITELIST = ("ene_eptotal", "ene_imp")

    def __init__(self):
        self.conn = None
        self.mysql_conn = None

    def connect(self) -> bool:
        """建立数据库连接

        连接参数统一由 core.pg_env.pg_params() 提供（keepalives/sslmode/超时都在那里），
        避免各模块各写一套默认值、漏配时连到不同的库。
        """
        try:
            self.conn = psycopg2.connect(**pg_params())
            with self.conn.cursor() as cur:
                cur.execute("SET statement_timeout = '60s'")
            self.connect_mysql()  # 尝试同时连接 MySQL（运行状态/告警表）
            return True
        except Exception as e:
            print(f"[TimescaleDB] 连接失败: {e}")
            self.conn = None
            return False

    def connect_mysql(self) -> bool:
        """连接 MySQL 业务数据库（运行状态/告警等字典和记录表）。
        连接信息从 AQA_MYSQL_* 环境变量读取，不可用时跳过不影响主流程。
        """
        if not HAS_PYMYSQL:
            print("[TimescaleDB] pymysql 未安装，MySQL 连接跳过")
            return False
        try:
            host = os.getenv("AQA_MYSQL_HOST") or os.getenv("SRC_MYSQL_HOST")
            if not host:
                return False
            self.mysql_conn = pymysql.connect(
                host=host,
                port=int(os.getenv("AQA_MYSQL_PORT") or os.getenv("SRC_MYSQL_PORT", "3306")),
                user=os.getenv("AQA_MYSQL_USER") or os.getenv("SRC_MYSQL_USER", "readonly_user"),
                password=os.getenv("AQA_MYSQL_PASSWORD") or os.getenv("SRC_MYSQL_PASSWORD", "CHANGE_ME"),
                database=os.getenv("AQA_MYSQL_DATABASE") or os.getenv("SRC_MYSQL_DB", "btr"),
                charset="utf8mb4",
                connect_timeout=10,
            )
            return True
        except Exception as e:
            print(f"[TimescaleDB] MySQL 连接失败: {e}")
            self.mysql_conn = None
            return False

    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()
            self.conn = None
        if self.mysql_conn:
            self.mysql_conn.close()
            self.mysql_conn = None

    def get_devices(self) -> List[Dict[str, Any]]:
        """获取设备列表——只返回管理员在"系统管理→设备列表"页里勾选为可见
        (visible_in_params=true) 的设备。哪些设备可见不再写死在代码里，见
        ensure_visible_in_params_column() 的迁移说明和 backend/routes/device_config.py。

        设备类型仍按 device_code 前缀分组显示：
        - 球磨机: BTR-QSDLQM-xxx
        - 合膏机: BTR-QSDLHG-xxx / BTR-QSDLHG02-xxx
        - 固化室: BTR-QSDLGH-xxx
        """
        if not self.conn:
            return []

        ensure_visible_in_params_column(self.conn)

        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SET statement_timeout = '5s'")
            cursor.execute("""
                SELECT di.id, di.device_id AS device_code, di.device_name,
                       CASE
                           WHEN di.device_id LIKE 'BTR-QSDLQM%' THEN '球磨机'
                           WHEN di.device_id LIKE 'BTR-QSDLHG%' THEN '合膏机'
                           WHEN di.device_id LIKE 'BTR-QSDLGH%' THEN '固化室'
                           ELSE '其他'
                       END AS device_type
                FROM device_info di
                WHERE di.visible_in_params = true
                ORDER BY device_type, di.id
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_energy_device_ids(self, device_code: str) -> List[str]:
        """查 device_energy_meter，返回 device_code 关联的电表 device_id 列表。

        一个生产设备可能对应多个电表（如固化室A/B区各一个），无关联返回 []（常态，
        绝大多数设备没有电表——调用方在空列表时应完全跳过能耗分支，不产生额外查询）。
        """
        if not self.conn:
            return []
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    "SELECT meter_device_id FROM device_energy_meter WHERE production_device_id = %s",
                    (device_code,),
                )
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"[TimescaleDB] 查询 device_energy_meter 失败: {e}")
            self.conn.rollback()
            return []

    def get_point_names(self, device_code: str) -> Dict[str, str]:
        """获取指定设备的点位编码到中文名称的映射

        优先从 dev_device_param 表查询（覆盖所有设备），
        再用 point_info 表补充，最后回退到 point_config 硬编码。
        返回: {p_name_code: display_name}
        """
        mapping: Dict[str, str] = {}

        if self.conn:
            # 1. 从 dev_device_param 表查询 (name -> description, 按 device_no)
            # device_ids 含 device_code 本身 + 关联电表(有能耗接入的设备)，让能耗
            # 点位名称跟着生产设备一起查出来，无关联电表时等价于原查询
            device_ids = [device_code] + self.get_energy_device_ids(device_code)
            try:
                with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """SELECT name AS p_name, description FROM dev_device_param
                           WHERE device_no = ANY(%s) AND description IS NOT NULL AND description != ''""",
                        (device_ids,),
                    )
                    for row in cursor.fetchall():
                        mapping[row["p_name"]] = row["description"]
            except Exception as e:
                print(f"[TimescaleDB] 查询 dev_device_param 失败: {e}")

            # 2. 用 point_info 表补充 mapping 中没有的
            if len(mapping) == 0:
                try:
                    with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                        cursor.execute(
                            "SELECT point_id, point_name FROM point_info WHERE belong_devide = %s",
                            (device_code,),
                        )
                        for row in cursor.fetchall():
                            if row["point_id"] not in mapping:
                                mapping[row["point_id"]] = row["point_name"]
                except Exception as e:
                    print(f"[TimescaleDB] 查询 point_info 失败: {e}")

        # 3. 最后回退到 point_config 硬编码
        if len(mapping) == 0:
            try:
                from modules.device_warning.ai_analysis.point_config import PROCESS_POINT_DISPLAY_NAMES
                mapping = dict(PROCESS_POINT_DISPLAY_NAMES.get(device_code, {}))
            except ImportError:
                pass

        return mapping

    def get_point_units(self, device_code: str) -> Dict[str, str]:
        """获取指定设备的点位编码到单位的映射（从 dev_device_param 表）"""
        units: Dict[str, str] = {}
        if not self.conn:
            return units
        device_ids = [device_code] + self.get_energy_device_ids(device_code)
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """SELECT name AS p_name, unit FROM dev_device_param
                       WHERE device_no = ANY(%s) AND unit IS NOT NULL AND unit != ''""",
                    (device_ids,),
                )
                for row in cursor.fetchall():
                    units[row["p_name"]] = row["unit"]
        except Exception as e:
            print(f"[TimescaleDB] 查询 dev_device_param units 失败: {e}")
        return units

    def get_points(self, device_code: str) -> List[Dict[str, Any]]:
        """获取指定设备的所有参数定义（从 dev_device_param 表），附带中文显示名和单位

        含关联电表(device_energy_meter)的能耗点位——跟工艺点位一起返回，让能耗
        数据作为生产设备自己的参数参与画像/阶段分析/AI诊断（这些都是按 device_code
        枚举参数，能耗挂在电表自己的 device_code 下时天然查不到）。

        能耗点位只保留 ene_eptotal(组合有功总电能) 和 ene_imp(正向有功电能)，
        其他电压电流功率因数等 29 个不参与参数分析展示。
        """
        if not self.conn:
            return []

        device_ids = [device_code] + self.get_energy_device_ids(device_code)
        _ENERGY_WHITELIST = set(self._ENERGY_POINT_WHITELIST)
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """SELECT name AS p_name, description, unit
                       FROM dev_device_param
                       WHERE device_no = ANY(%s)
                       ORDER BY sort_num NULLS LAST, id""",
                    (device_ids,),
                )
                return [
                    {
                        "p_name": row["p_name"],
                        "display_name": row["description"] or row["p_name"],
                        "unit": row["unit"] or "",
                    }
                    for row in cursor.fetchall()
                    if not (row["p_name"].startswith("ene_") and row["p_name"] not in _ENERGY_WHITELIST)
                ]
        except Exception as e:
            print(f"[TimescaleDB] 查询 dev_device_param 点位列表失败: {e}")
            return []

    def get_param_data(
        self,
        device_code: str,
        p_name: Optional[str] = None,
        p_names: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        """
        查询设备参数时间序列数据

        数据源：UNION ALL device_alarm_info（工艺点位，实时点位采集表）+
        device_energy_info（电表能耗点位，2026-07 贝特瑞电表接入起补充，mqtt_etl 的
        EnergyMessageParser 写入）。两边 device_id 值域不重叠（工艺设备编码如
        BTR-QSDLQM-01-001 vs 电表网关编码如 c3w9ot7k_EMQSDLQM-01-001），能耗分支改按
        get_energy_device_ids(device_code) 查到的关联电表 id 过滤（经 device_energy_meter
        映射），而不是直接拿 device_code 去匹配——否则能耗分支永远查不到行。无关联电表
        的设备（绝大多数）不会 UNION 能耗分支，行为跟改动前一致。
        旧表 dev_device_param_detail_record / MySQL dev_device_param_record 已于
        2026-04-21 02:00 停采，故切换至此表。字段映射：
            device_id -> device_code, point_id -> p_name,
            point_time -> gather_time, raw_json 内点位值 -> p_value

        注意：device_alarm_info.point_value 是 integer，会截断小数（如 122.7 存成
        122），全精度值由 mqtt_etl 写入时同步填充到 point_value_full(NUMERIC)，
        查询直接用 COALESCE(point_value_full, point_value) 无需 LATERAL JSONB 拆包；
        device_energy_info.point_value 已经是 numeric(14,4)，直接转 text 即可。

        Args:
            device_code: 设备编号
            p_name: 点位名称（可选，为空则查询该设备所有点位）
            p_names: 多个点位名称列表（可选，优先级高于 p_name）
            start_time: 开始时间
            end_time: 结束时间
            limit: 最大返回条数
        """
        if not self.conn:
            return []

        def build_conditions(alias: str, id_expr: str, id_params: list) -> tuple:
            conditions = [f"{alias}.device_id {id_expr}"]
            branch_params: List[Any] = list(id_params)
            if p_names:
                conditions.append(f"{alias}.point_id = ANY(%s)")
                branch_params.append(p_names)
            elif p_name:
                conditions.append(f"{alias}.point_id = %s")
                branch_params.append(p_name)
            if start_time:
                conditions.append(f"{alias}.point_time >= %s")
                branch_params.append(start_time)
            if end_time:
                conditions.append(f"{alias}.point_time <= %s")
                branch_params.append(end_time)
            return " AND ".join(conditions), branch_params

        alarm_where, alarm_params = build_conditions("a", "= %s", [device_code])

        alarm_select = """
            SELECT a.device_id AS device_code, a.south_driver_name AS device_name,
                   a.point_id AS p_name, a.point_time AS gather_time,
                   COALESCE(a.point_value_full::text, a.point_value::text) AS p_value
            FROM device_alarm_info a
            WHERE {}
        """.format(alarm_where)

        selects = [alarm_select]
        params = list(alarm_params)

        # 关联电表(device_energy_meter)存在时才 UNION 能耗分支；无关联时可能是电表
        # 设备本身（如 ywjui12w_EMQSDLHG-01-004），直接用 device_code 查能耗表
        meter_ids = self.get_energy_device_ids(device_code)
        if not meter_ids:
            meter_ids = [device_code]
        if meter_ids:
            energy_where, energy_params = build_conditions("e", "= ANY(%s)", [meter_ids])
            # 能耗点位白名单：只返回 ene_eptotal / ene_imp，其余电压电流功率因数不展示
            energy_where += " AND e.point_id IN %s"
            energy_params.append(self._ENERGY_POINT_WHITELIST)
            energy_select = """
                SELECT e.device_id AS device_code, e.south_driver_name AS device_name,
                       e.point_id AS p_name, e.point_time AS gather_time,
                       e.point_value::text AS p_value
                FROM device_energy_info e
                WHERE {}
            """.format(energy_where)
            selects.append(energy_select)
            params += energy_params

        union_sql = " UNION ALL ".join(f"({s})" for s in selects)

        # 始终加 LIMIT，避免大时间跨度返回海量行导致超时或 OOM
        query = f"{union_sql} ORDER BY gather_time ASC LIMIT %s"
        params.append(limit)

        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, tuple(params))
            rows = [dict(row) for row in cursor.fetchall()]

        for row in rows:
            row["p_value_raw"] = row["p_value"]
            try:
                v = float(row["p_value"])
                row["p_value_num"] = int(v) if v.is_integer() else v
            except (ValueError, TypeError):
                row["p_value_num"] = None

        return rows

    # 自动粒度档位：(范围上限小时, interval 名, PG INTERVAL)
    _AGG_LEVELS = [
        (6, "5min", "5 minutes"),
        (24, "15min", "15 minutes"),
        (72, "1hour", "1 hour"),
        (168, "4hour", "4 hours"),
        (None, "1day", "1 day"),  # > 168h
    ]
    _AGG_INTERVAL_MAP = {
        "5min": "5 minutes", "15min": "15 minutes", "1hour": "1 hour",
        "4hour": "4 hours", "1day": "1 day",
    }

    @classmethod
    def resolve_interval(cls, hours: float, interval: str = "auto") -> str:
        """根据时间跨度自动选择聚合粒度（interval=auto 时）。"""
        if interval and interval != "auto":
            return interval if interval in cls._AGG_INTERVAL_MAP else "1hour"
        for upper, name, _ in cls._AGG_LEVELS:
            if upper is None or hours <= upper:
                return name
        return "1day"

    def get_param_data_aggregated(
        self,
        device_code: str,
        start_time: datetime,
        end_time: datetime,
        p_name: Optional[str] = None,
        p_names: Optional[List[str]] = None,
        interval: str = "auto",
    ) -> Dict[str, Any]:
        """
        多粒度聚合参数数据（用于大时间跨度绘图，避免一次性返回海量原始点）。

        数据源 UNION ALL device_alarm_info + device_energy_info（能耗分支按
        get_energy_device_ids(device_code) 映射到的关联电表 id 过滤，见 get_param_data
        同样的说明），取值逻辑与 get_param_data 一致（工艺点位 point_value_full 优先，
        能耗点位 point_value 本身就是 numeric(14,4)）。interval >= 1hour 时走
        TimescaleDB 连续聚合物化视图（device_alarm_hourly / device_energy_hourly），
        粗粒度用 time_bucket 在视图上二次 rollup，避免扫原始表。
        """
        if not self.conn:
            return {"interval": interval, "series": {}}

        hours = (end_time - start_time).total_seconds() / 3600
        interval = self.resolve_interval(hours, interval)

        # >= 1hour 走连续聚合物化视图，秒出
        if interval in ("1hour", "4hour", "1day"):
            result = self._aggregated_from_cagg(device_code, start_time, end_time, p_name, p_names, interval)
            if result is not None and result.get("series"):
                return result
            # cagg 视图对该时间范围无数据（例如视图保留期短于原始表），
            # 回退到原始表聚合，保证用户能看到历史数据

        # 5min / 15min 仍然扫原始表（跨度小，行数可控，且有 point_value_full 无 LATERAL）
        return self._aggregated_from_raw(device_code, start_time, end_time, p_name, p_names, interval)

    def _aggregated_from_cagg(
        self,
        device_code: str,
        start_time: datetime,
        end_time: datetime,
        p_name: Optional[str],
        p_names: Optional[List[str]],
        interval: str,
    ) -> Optional[Dict[str, Any]]:
        """从连续聚合物化视图查询（interval >= 1hour），秒出。

        device_alarm_hourly / device_energy_hourly 是按 (device_id, point_id, 1h bucket)
        预计算好的 avg/min/max/sum/count，粗粒度用 time_bucket 在视图上二次 rollup。
        比实时扫原始表快 1-2 个数量级。
        返回 None 表示视图不存在或查询失败，调用方应回退到原始表。
        """
        pg_interval = f"INTERVAL '{self._AGG_INTERVAL_MAP[interval]}'"

        if p_names:
            p_name_filter = "AND point_id = ANY(%s)"
        elif p_name:
            p_name_filter = "AND point_id = %s"
        else:
            p_name_filter = ""

        subs = []
        params: List[Any] = []

        # alarm cagg
        alarm_sql = """
            SELECT point_id AS p_name,
                time_bucket({}, bucket) AS bucket,
                SUM(sum_val) / NULLIF(SUM(cnt), 0) AS avg_val,
                MIN(min_val) AS min_val,
                MAX(max_val) AS max_val,
                NULL::double precision AS std_val,
                SUM(cnt)::bigint AS cnt
            FROM device_alarm_hourly
            WHERE device_id = %s
              AND bucket >= %s AND bucket < %s
              {}
            GROUP BY point_id, bucket
        """.format(pg_interval, p_name_filter)
        subs.append(alarm_sql)
        params.extend([device_code, start_time, end_time])
        if p_names:
            params.append(p_names)
        elif p_name:
            params.append(p_name)

        # energy cagg（有关联电表时用映射，否则可能是电表设备本身直接用 device_code）
        meter_ids = self.get_energy_device_ids(device_code)
        if not meter_ids:
            meter_ids = [device_code]
        if meter_ids:
            energy_sql = """
                SELECT point_id AS p_name,
                    time_bucket({}, bucket) AS bucket,
                    SUM(sum_val) / NULLIF(SUM(cnt), 0) AS avg_val,
                    MIN(min_val) AS min_val,
                    MAX(max_val) AS max_val,
                    NULL::double precision AS std_val,
                    SUM(cnt)::bigint AS cnt
                FROM device_energy_hourly
                WHERE device_id = ANY(%s)
                  AND point_id IN %s
                  AND bucket >= %s AND bucket < %s
                  {}
                GROUP BY point_id, bucket
            """.format(pg_interval, p_name_filter)
            subs.append(energy_sql)
            params.extend([meter_ids, self._ENERGY_POINT_WHITELIST, start_time, end_time])
            if p_names:
                params.append(p_names)
            elif p_name:
                params.append(p_name)

        union_sql = " UNION ALL ".join(subs)
        query = f"{union_sql} ORDER BY p_name, bucket"

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, tuple(params))
                raw = [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[TimescaleDB] cagg 查询失败，回退原始表: {e}")
            return None

        return self._build_aggregated_result(raw, interval)

    def _aggregated_from_raw(
        self,
        device_code: str,
        start_time: datetime,
        end_time: datetime,
        p_name: Optional[str],
        p_names: Optional[List[str]],
        interval: str,
    ) -> Dict[str, Any]:
        """从原始表实时聚合（interval < 1hour 时使用，有 point_value_full 列，无需 LATERAL）"""
        pg_interval = f"INTERVAL '{self._AGG_INTERVAL_MAP[interval]}'"

        def build_conditions(alias: str, id_expr: str, id_params: list) -> tuple:
            conditions = [f"{alias}.device_id {id_expr}", f"{alias}.point_time >= %s", f"{alias}.point_time <= %s"]
            branch_params: List[Any] = list(id_params) + [start_time, end_time]
            if p_names:
                conditions.append(f"{alias}.point_id = ANY(%s)")
                branch_params.append(p_names)
            elif p_name:
                conditions.append(f"{alias}.point_id = %s")
                branch_params.append(p_name)
            return " AND ".join(conditions), branch_params

        alarm_where, alarm_params = build_conditions("a", "= %s", [device_code])

        alarm_cast_expr = (
            "CASE WHEN a.point_value_full IS NOT NULL THEN a.point_value_full::double precision "
            "WHEN a.point_value IS NOT NULL THEN a.point_value::double precision "
            "ELSE NULL END"
        )

        alarm_sub = """
            SELECT a.point_id AS p_name, a.point_time AS gather_time,
                {alarm_cast} AS p_value_num
            FROM device_alarm_info a
            WHERE {alarm_where}
        """.format(alarm_cast=alarm_cast_expr, alarm_where=alarm_where)

        subs = [alarm_sub]
        params = list(alarm_params)

        # 关联电表(device_energy_meter)存在时用映射，否则可能是电表设备直接用 device_code
        meter_ids = self.get_energy_device_ids(device_code)
        if not meter_ids:
            meter_ids = [device_code]
        if meter_ids:
            energy_where, energy_params = build_conditions("e", "= ANY(%s)", [meter_ids])
            energy_where += " AND e.point_id IN %s"
            energy_params.append(self._ENERGY_POINT_WHITELIST)
            energy_sub = """
                SELECT e.point_id AS p_name, e.point_time AS gather_time,
                    e.point_value::double precision AS p_value_num
                FROM device_energy_info e
                WHERE {energy_where}
            """.format(energy_where=energy_where)
            subs.append(energy_sub)
            params += energy_params

        union_sub_sql = " UNION ALL ".join(subs)

        query = """
            SELECT
                p_name,
                time_bucket({}, gather_time) AS bucket,
                AVG(p_value_num) AS avg_val,
                MIN(p_value_num) AS min_val,
                MAX(p_value_num) AS max_val,
                STDDEV(p_value_num) AS std_val,
                COUNT(*) AS cnt
            FROM ({}) sub
            WHERE p_value_num IS NOT NULL
            GROUP BY p_name, bucket
            ORDER BY p_name, bucket
        """.format(pg_interval, union_sub_sql)

        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, tuple(params))
            raw = [dict(row) for row in cursor.fetchall()]

        return self._build_aggregated_result(raw, interval)

    @staticmethod
    def _build_aggregated_result(raw: list, interval: str) -> Dict[str, Any]:
        grouped: Dict[str, List[Dict]] = {}
        for row in raw:
            key = row["p_name"]
            b = row["bucket"]
            # cagg 视图(NUMERIC 列)返回 Decimal，JSON 无法序列化，统一转 float
            grouped.setdefault(key, []).append({
                "time": b.strftime("%Y-%m-%d %H:%M:%S") if isinstance(b, datetime) else str(b),
                "value": round(float(row["avg_val"]), 3) if row["avg_val"] is not None else None,
                "min": round(float(row["min_val"]), 3) if row["min_val"] is not None else None,
                "max": round(float(row["max_val"]), 3) if row["max_val"] is not None else None,
                "std": round(float(row["std_val"]), 3) if row["std_val"] is not None else None,
                "count": row["cnt"],
            })
        return {"interval": interval, "series": grouped}

    def get_latest_param_time(self, device_code: str) -> Optional[datetime]:
        """该设备最新点位采集时间(device_alarm_info)。

        带时间下界逐步放宽以走 point_time 索引(秒回)，避免全表 MAX 扫描。
        """
        if not self.conn:
            return None
        with self.conn.cursor() as cursor:
            for days in (2, 30, 365):
                cursor.execute(
                    """SELECT MAX(point_time) FROM device_alarm_info
                       WHERE device_id = %s
                         AND point_time > now() - (%s || ' days')::interval""",
                    (device_code, days),
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    return row[0]
        return None

    def get_device_id_by_code(self, device_code: str) -> Optional[int]:
        """根据 device_code（业务编号）查找对应的数字 device_id（dev_device_status_record 使用）"""
        if not self.conn:
            return None
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT id FROM device_info WHERE device_id = %s LIMIT 1", (device_code,))
            row = cursor.fetchone()
            return row[0] if row else None

    def get_running_status_code(self) -> Optional[int]:
        """获取'运行'状态对应的状态码（从 MySQL dev_device_status 表）"""
        if not self.mysql_conn:
            return None
        try:
            with self.mysql_conn.cursor() as cursor:
                cursor.execute("SELECT code FROM dev_device_status WHERE status = '运行' LIMIT 1")
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            print(f"[TimescaleDB] 查询运行状态码失败: {e}")
            return None

    def get_running_periods(
        self,
        device_id: int,
        status_code: int,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """获取设备在指定时间范围内的运行时段（从 MySQL dev_device_status_record 表）"""
        if not self.mysql_conn:
            return []

        try:
            with self.mysql_conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT start_time, end_time, duration
                    FROM dev_device_status_record
                    WHERE device_id = %s
                      AND status = %s
                      AND start_time < %s
                      AND (end_time IS NULL OR end_time > %s)
                    ORDER BY start_time ASC
                """, (device_id, status_code, end_time, start_time))
                rows = cursor.fetchall()
        except Exception as e:
            print(f"[TimescaleDB] 查询运行时段失败: {e}")
            return []

        for row in rows:
            if isinstance(row.get("start_time"), datetime):
                row["start_time"] = row["start_time"].strftime("%Y-%m-%d %H:%M:%S")
            if row.get("end_time") and isinstance(row["end_time"], datetime):
                row["end_time"] = row["end_time"].strftime("%Y-%m-%d %H:%M:%S")
        return rows

    def get_alarm_events(
        self,
        device_id: int,
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """获取设备在指定时间范围内的所有状态/告警事件（从 MySQL dev_device_status_record 表）"""
        if not self.mysql_conn:
            return []

        try:
            with self.mysql_conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT r.status, s.name AS status_name,
                           r.start_time, r.end_time, r.duration,
                           r.qualified_count, r.unqualified_count
                    FROM dev_device_status_record r
                    LEFT JOIN dev_device_status s ON s.code = r.status
                    WHERE r.device_id = %s
                      AND r.start_time < %s
                      AND (r.end_time IS NULL OR r.end_time > %s)
                    ORDER BY r.start_time ASC
                """, (device_id, end_time, start_time))
                rows = cursor.fetchall()
        except Exception as e:
            print(f"[TimescaleDB] 查询告警事件失败: {e}")
            return []

        for row in rows:
            for key in ("start_time", "end_time"):
                if isinstance(row.get(key), datetime):
                    row[key] = row[key].strftime("%Y-%m-%d %H:%M:%S")
        return rows

    def get_compressed_param_data(
        self,
        device_code: str,
        p_name: Optional[str],
        start_time: datetime,
        end_time: datetime,
        max_hours: int = 72,
        max_points_per_series: int = 288,
        running_periods: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        获取压缩后的参数数据（用于 AI 分析）

        数据源：device_alarm_info（实时点位采集表），与 get_param_data 一致。
        旧表 dev_device_param_detail_record 已于 2026-04-21 02:00 停采，
        故此处一并切换，避免 AI 分析读到停采的旧数据。
        全精度值取自 raw_json->devices[]->points[]->point_value，
        回退到 point_value 列（integer，会截断小数）。

        按小时聚合：avg / min / max / count / stddev。
        如果提供了 running_periods，则只查询运行时段内的数据；
        否则如果时间范围超过 max_hours，截取最后 max_hours。
        """
        if not self.conn:
            return {}

        # 构建时间过滤条件：按运行时段 OR 整体时间范围
        if running_periods:
            # 将运行时段转为 SQL OR 条件
            period_conds = []
            period_params: List[Any] = []
            actual_start = None
            actual_end = None
            for p in running_periods:
                p_start = p["start_time"]
                p_end = p.get("end_time")
                if isinstance(p_start, str):
                    p_start = datetime.strptime(p_start, "%Y-%m-%d %H:%M:%S")
                if p_end and isinstance(p_end, str):
                    p_end = datetime.strptime(p_end, "%Y-%m-%d %H:%M:%S")

                if actual_start is None or p_start < actual_start:
                    actual_start = p_start
                if p_end is None:
                    actual_end = end_time
                elif actual_end is None or p_end > actual_end:
                    actual_end = p_end

                period_conds.append("(a.point_time >= %s AND a.point_time < %s)")
                period_params.extend([p_start, p_end or end_time])

            time_cond = "(" + " OR ".join(period_conds) + ")"
            total_hours = ((actual_end or end_time) - (actual_start or start_time)).total_seconds() / 3600
            query_start = actual_start or start_time
            query_end = actual_end or end_time
        else:
            # 如果范围超过 max_hours，截取最后 max_hours
            total_hours = (end_time - start_time).total_seconds() / 3600
            if total_hours > max_hours:
                start_time = end_time - timedelta(hours=max_hours)
            query_start = start_time
            query_end = end_time
            time_cond = "a.point_time >= %s AND a.point_time <= %s"
            period_params = [start_time, end_time]

        conditions = [
            "a.device_id = %s",
            time_cond,
        ]
        params: List[Any] = [device_code] + period_params

        if p_name:
            conditions.append("a.point_id = %s")
            params.append(p_name)

        where = " AND ".join(conditions)

        # 优先用 point_value_full（NUMERIC 全精度），无则回退 point_value（INTEGER 截断）
        cast_expr = (
            "CASE WHEN a.point_value_full IS NOT NULL THEN a.point_value_full::double precision "
            "WHEN a.point_value IS NOT NULL THEN a.point_value::double precision "
            "ELSE NULL END"
        )

        query = """
            SELECT
                p_name,
                date_trunc('hour', gather_time) AS hour_bucket,
                COUNT(*) AS cnt,
                AVG(p_value_num) AS avg_val,
                MIN(p_value_num) AS min_val,
                MAX(p_value_num) AS max_val,
                STDDEV(p_value_num) AS std_val
            FROM (
                SELECT a.point_id AS p_name, a.point_time AS gather_time,
                    {} AS p_value_num
                FROM device_alarm_info a
                WHERE {}
            ) sub
            WHERE p_value_num IS NOT NULL
            GROUP BY p_name, hour_bucket
            ORDER BY p_name, hour_bucket
            LIMIT %s
        """.format(cast_expr, where)
        params.append(max_points_per_series * 20)

        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, tuple(params))
            raw = [dict(row) for row in cursor.fetchall()]

        grouped: Dict[str, List[Dict]] = {}
        for row in raw:
            key = row["p_name"]
            if key not in grouped:
                grouped[key] = []
            hb = row["hour_bucket"]
            grouped[key].append({
                "hour": hb.strftime("%Y-%m-%d %H:00") if isinstance(hb, datetime) else str(hb),
                "count": row["cnt"],
                "avg": round(row["avg_val"], 2) if row["avg_val"] is not None else None,
                "min": round(row["min_val"], 2) if row["min_val"] is not None else None,
                "max": round(row["max_val"], 2) if row["max_val"] is not None else None,
                "std": round(row["std_val"], 2) if row["std_val"] is not None else None,
            })

        return {
            "start_time": query_start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": query_end.strftime("%Y-%m-%d %H:%M:%S"),
            "total_hours": round(total_hours, 1),
            "series": grouped,
        }
