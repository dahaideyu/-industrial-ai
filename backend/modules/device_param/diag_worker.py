# cython: annotation_typing=False, infer_types=False, language_level=3
"""定时全设备 AI 自主诊断简报：跑 agentic_param.run_diagnosis 落库，供日报/页面读缓存。

每台设备一次多轮 LLM，较慢，逐设备 try/except 互不阻断；幂等(同日 ON CONFLICT 覆盖)。
"""

import json
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor

from core.job_logger import JobLogger
from .services import TimescaleDB


def ensure_diag_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_diagnosis (
                device_code VARCHAR(64) NOT NULL,
                eval_date   DATE        NOT NULL,
                diagnosis   TEXT,
                risk_hint   VARCHAR(16),
                trace       JSONB,
                rounds      SMALLINT,
                elapsed_ms  INTEGER,
                created_at  TIMESTAMPTZ DEFAULT now(),
                PRIMARY KEY (device_code, eval_date)
            )
        """)
        cur.execute("""CREATE INDEX IF NOT EXISTS ix_device_diagnosis_date
                       ON device_diagnosis (eval_date, risk_hint)""")
    conn.commit()


def _risk_hint(text: str) -> str:
    """从诊断文本粗提风险等级（仅供排序/筛选，非权威）。"""
    t = text or ""
    if "危险" in t:
        return "critical"
    if "告警" in t or "警告" in t:
        return "warning"
    if "关注" in t:
        return "attention"
    return "normal"


def _upsert(conn, device_code: str, eval_date: date, res: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO device_diagnosis
              (device_code, eval_date, diagnosis, risk_hint, trace, rounds, elapsed_ms, created_at)
            VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s, now())
            ON CONFLICT (device_code, eval_date) DO UPDATE SET
              diagnosis=EXCLUDED.diagnosis, risk_hint=EXCLUDED.risk_hint,
              trace=EXCLUDED.trace, rounds=EXCLUDED.rounds,
              elapsed_ms=EXCLUDED.elapsed_ms, created_at=now()
        """, (device_code, eval_date, res.get("diagnosis", ""),
              _risk_hint(res.get("diagnosis", "")),
              json.dumps(res.get("trace", []), ensure_ascii=False),
              res.get("rounds"), res.get("elapsed_ms")))
    conn.commit()


def run_diagnosis_job(report_date: Optional[date] = None,
                      device_code: Optional[str] = None) -> Dict[str, Any]:
    """全设备(或单设备)跑诊断 agent，落 device_diagnosis。"""
    if report_date is None:
        report_date = date.today()
    jlog = JobLogger(job_type="deviceParamDiagnosis",
                     report_date=report_date.strftime("%Y-%m-%d"))
    jlog.print_separator()
    jlog.info(f"AI 自主诊断简报开始 eval={report_date} device={device_code or '全部'}")

    db = TimescaleDB()
    if not db.connect():
        jlog.error("TimescaleDB 连接失败")
        return {"ok": False, "error": "db_connect_failed"}

    summary = {"ok": True, "eval_date": str(report_date), "devices": 0,
               "done": 0, "failed": 0, "by_risk": {}}
    try:
        ensure_diag_table(db.conn)
        from .agentic_param import run_diagnosis

        devices = ([{"device_code": device_code}] if device_code else db.get_devices())
        summary["devices"] = len(devices)
        for dev in devices:
            dcode = dev["device_code"]
            try:
                res = run_diagnosis(dcode)
                _upsert(db.conn, dcode, report_date, res)
                hint = _risk_hint(res.get("diagnosis", ""))
                summary["by_risk"][hint] = summary["by_risk"].get(hint, 0) + 1
                summary["done"] += 1
                jlog.info(f"[{dcode}] 诊断完成 risk={hint} rounds={res.get('rounds')} "
                          f"tools={[t['tool'] for t in res.get('trace', [])]}")
            except Exception as e:
                db.conn.rollback()
                summary["failed"] += 1
                jlog.error(f"[{dcode}] 诊断失败: {e}", exc_info=True)
        jlog.info(f"完成: {summary['done']}/{summary['devices']} 成功, "
                  f"{summary['failed']} 失败, 风险分布={summary['by_risk']}")
        jlog.print_separator()
        return summary
    finally:
        db.close()


def read_latest(conn, device_code: str) -> Optional[Dict[str, Any]]:
    """读该设备最新诊断缓存。"""
    ensure_diag_table(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""SELECT device_code, eval_date, diagnosis, risk_hint, trace,
                              rounds, elapsed_ms, created_at
                       FROM device_diagnosis WHERE device_code=%s
                       ORDER BY eval_date DESC LIMIT 1""", (device_code,))
        r = cur.fetchone()
    if not r:
        return None
    r = dict(r)
    r["eval_date"] = str(r["eval_date"])
    r["created_at"] = str(r["created_at"])
    return r
