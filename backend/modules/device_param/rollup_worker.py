# cython: annotation_typing=False, infer_types=False, language_level=3
"""设备参数 趋势漂移 批量任务：算日级统计写底表 + 算漂移写预警快照。

- 夜间增量：run_rollup_job() 默认只处理昨天（最近一个完整日）。
- 首次回填：run_rollup_job(backfill_days=90) 一次性补算最近 90 天。
- 幂等：底表/快照表均 ON CONFLICT，重跑同日覆盖。逐设备/逐天 try/except 互不阻断。
"""

from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Set

from core.job_logger import JobLogger
from .services import TimescaleDB
from . import stats_store as store


def _existing_days(conn, device_code: str, start: date, end: date,
                   running_only: bool) -> Set[date]:
    """该设备底表中 [start,end] 已有统计的 stat_date 集合（用于回填时跳过已算）。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT stat_date FROM device_param_daily_stats
            WHERE device_code=%s AND stat_date BETWEEN %s AND %s AND running_only=%s
        """, (device_code, start, end, running_only))
        return {row[0] for row in cur.fetchall()}


def run_rollup_job(
    report_date: Optional[date] = None,
    backfill_days: int = 0,
    device_code: Optional[str] = None,
    running_only: bool = True,
    force: bool = False,
) -> Dict[str, Any]:
    """主入口。

    Args:
        report_date: 评估日（最近完整日）。缺省=昨天。
        backfill_days: 向前回填天数（0=只算 report_date 当天）。
        device_code: 仅处理指定设备（缺省=全部设备）。
        running_only: 统计是否仅运行时段（默认 True）。
        force: True 则回填时重算已存在的日（默认跳过已算）。
    """
    if report_date is None:
        report_date = (datetime.now() - timedelta(days=1)).date()
    start_day = report_date - timedelta(days=max(backfill_days, 0))

    jlog = JobLogger(job_type="deviceParamRollup",
                     report_date=report_date.strftime("%Y-%m-%d"))
    jlog.print_separator()
    jlog.info(f"参数趋势汇总开始 eval={report_date} 回填={backfill_days}天 "
              f"窗口=[{start_day}..{report_date}] running_only={running_only} force={force}")

    db = TimescaleDB()
    if not db.connect():
        jlog.error("TimescaleDB 连接失败")
        return {"ok": False, "error": "db_connect_failed"}

    summary = {"ok": True, "eval_date": str(report_date),
               "window": [str(start_day), str(report_date)],
               "devices": 0, "device_failed": 0,
               "day_rows": 0, "days_done": 0, "days_skipped": 0,
               "alerts": 0, "alert_devices_failed": 0, "details": []}
    try:
        store.ensure_tables(db.conn)

        if device_code:
            devices = [{"device_code": device_code}]
        else:
            devices = db.get_devices()
        summary["devices"] = len(devices)
        jlog.info(f"待处理设备数: {len(devices)}")

        for dev in devices:
            dcode = dev["device_code"]
            dev_rows = 0
            dev_days = 0
            dev_skipped = 0
            try:
                existing = (set() if force else
                            _existing_days(db.conn, dcode, start_day, report_date,
                                           running_only))
                # 从最近的天往回算：7/30 天视图最先有数据(回填大跨度时体验更好)
                day = report_date
                while day >= start_day:
                    if day in existing:
                        dev_skipped += 1
                        day -= timedelta(days=1)
                        continue
                    try:
                        rows = store.compute_daily_stats(db, dcode, day, running_only)
                        n = store.upsert_daily_stats(db.conn, rows)
                        dev_rows += n
                        dev_days += 1
                    except Exception as e:
                        db.conn.rollback()
                        jlog.error(f"[{dcode}] {day} 日统计失败: {e}", exc_info=True)
                    day -= timedelta(days=1)

                # 漂移预警（评估日）
                try:
                    n_alert = store.compute_trend_alerts(db.conn, db, dcode,
                                                         report_date, running_only)
                    summary["alerts"] += n_alert
                except Exception as e:
                    db.conn.rollback()
                    summary["alert_devices_failed"] += 1
                    jlog.error(f"[{dcode}] 漂移预警失败: {e}", exc_info=True)

                summary["day_rows"] += dev_rows
                summary["days_done"] += dev_days
                summary["days_skipped"] += dev_skipped
                jlog.info(f"[{dcode}] 写入 {dev_rows} 行 / {dev_days} 天 "
                          f"(跳过 {dev_skipped} 已算天)")
            except Exception as e:
                summary["device_failed"] += 1
                jlog.error(f"[{dcode}] 处理失败: {e}", exc_info=True)

        jlog.info(f"完成: 设备 {summary['devices']} (失败 {summary['device_failed']}) "
                  f"日统计 {summary['day_rows']} 行 / {summary['days_done']} 天 "
                  f"预警 {summary['alerts']} 条")
        jlog.print_separator()
        return summary
    finally:
        db.close()
