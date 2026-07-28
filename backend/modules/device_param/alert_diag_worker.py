# cython: annotation_typing=False, infer_types=False, language_level=3
"""定时知识库诊断：对当日 device_param_trend_alert 里**全部**报警(含 info/正常)，
逐条结合知识库生成分析并落 device_param_alert_diagnosis，供页面/日报读缓存。

- 每条报警一次 RAGFlow 知识库对话，较慢；逐设备/逐条 try/except 互不阻断。
- 不再区分严重度——info/正常 也会生成"相关信息汇总"（见 alert_diagnosis.build_question），
  每天都留一条详细记录方便查看，不是只有出问题才写库。幂等（同 key ON CONFLICT 覆盖，
  eval_date 变化则是新的一行，即"每天一条历史记录"）。
- 全量诊断意味着 RAGFlow 调用量=设备数×参数数×阶段数（远多于原来只诊断 warning/critical），
  如果设备/参数规模大导致跑得太久或知识库调用成本太高，用 max_per_device 限流，
  或用 baseline_days 只跑某个窗口。
- 应排在参数趋势汇总(run_rollup_job)之后跑（需先有报警快照）。
"""

from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

from core.job_logger import JobLogger
from .services import TimescaleDB
from . import stats_store as store
from . import alert_diagnosis


def run_alert_diag_job(report_date: Optional[date] = None,
                       device_code: Optional[str] = None,
                       baseline_days: Optional[int] = None,
                       max_per_device: int = 0) -> Dict[str, Any]:
    """主入口。

    Args:
        report_date: 评估日。缺省=按各设备最新报警评估日（对齐 rollup 产出）。
        device_code: 仅处理指定设备（缺省=全部）。
        baseline_days: 仅诊断某窗口的报警（缺省=全部窗口，含 7 天分阶段与 30 天整天）。
        max_per_device: 每设备最多诊断条数（0=不限，即全部报警包括 info 都诊断）；
            按严重度→变化率已排序，非 0 时截断保留最严重的排在前面几条。
    """
    label = report_date.strftime("%Y-%m-%d") if report_date else "latest"
    jlog = JobLogger(job_type="deviceParamAlertDiag", report_date=label)
    jlog.print_separator()
    jlog.info(f"分阶段报警知识库诊断开始 eval={label} device={device_code or '全部'} "
              f"baseline_days={baseline_days or '全部'} max/设备={max_per_device or '不限'}")

    db = TimescaleDB()
    if not db.connect():
        jlog.error("TimescaleDB 连接失败")
        return {"ok": False, "error": "db_connect_failed"}

    summary = {"ok": True, "eval_date": label, "devices": 0, "device_failed": 0,
               "alerts_seen": 0, "diagnosed": 0, "failed": 0}
    try:
        store.ensure_tables(db.conn)
        alert_diagnosis.ensure_table(db.conn)

        devices = ([{"device_code": device_code}] if device_code else db.get_devices())
        summary["devices"] = len(devices)
        jlog.info(f"待处理设备数: {len(devices)}")

        for dev in devices:
            dcode = dev["device_code"]
            try:
                alerts = store.read_trend_alerts(db.conn, dcode, eval_date=report_date,
                                                 baseline_days=baseline_days)
                summary["alerts_seen"] += len(alerts)
                # 不再按severity过滤：全部报警(含info/正常)都要每天生成一条记录
                todo = alerts
                if max_per_device and len(todo) > max_per_device:
                    todo = todo[:max_per_device]

                dev_done = 0
                for a in todo:
                    try:
                        alert_diagnosis.diagnose_alert(db, a)
                        dev_done += 1
                        summary["diagnosed"] += 1
                    except Exception as e:
                        db.conn.rollback()
                        summary["failed"] += 1
                        jlog.error(f"[{dcode}] 报警 {a.get('metric')}@阶段{a.get('stage')} "
                                   f"诊断失败: {e}", exc_info=True)
                if todo:
                    jlog.info(f"[{dcode}] 诊断 {dev_done}/{len(todo)} 条 (共 {len(alerts)} 条)")
            except Exception as e:
                db.conn.rollback()
                summary["device_failed"] += 1
                jlog.error(f"[{dcode}] 处理失败: {e}", exc_info=True)

        jlog.info(f"完成: 设备 {summary['devices']} (失败 {summary['device_failed']}) "
                  f"诊断 {summary['diagnosed']} 条 (失败 {summary['failed']})")
        jlog.print_separator()
        return summary
    finally:
        db.close()
