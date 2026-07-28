""""AI 分析"按钮（原始参数/特征视图页签，一次性 LLM 解读当前时间段数据）的结果留痕。

与 device_diagnosis(自主诊断简报)、device_param_alert_diagnosis(报警知识库诊断) 是三张
独立的表——这里只是"我看了一眼数据、AI 说了什么"的流水记录，不代表报警/问题判定，
故不复用那两张表，避免把普通分析和报警/问题诊断混在一起。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_param_analysis_log (
                id           SERIAL PRIMARY KEY,
                device_code  VARCHAR(64) NOT NULL,
                device_name  VARCHAR(128),
                start_time   TIMESTAMP,
                end_time     TIMESTAMP,
                running_only BOOLEAN,
                analysis     TEXT,
                created_at   TIMESTAMPTZ DEFAULT now()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS ix_device_param_analysis_log_device
            ON device_param_analysis_log (device_code, created_at DESC)
        """)
    conn.commit()


def save(conn, device_code: str, device_name: Optional[str],
         start_time, end_time, running_only: bool, analysis: str) -> None:
    """写入一条分析记录。best-effort，调用方失败也不应阻断给用户的响应。"""
    ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO device_param_analysis_log
              (device_code, device_name, start_time, end_time, running_only, analysis)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (device_code, device_name, start_time, end_time, running_only, analysis))
    conn.commit()


def list_recent(conn, device_code: str, limit: int = 20) -> List[Dict[str, Any]]:
    ensure_table(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, device_code, device_name, start_time, end_time,
                   running_only, analysis, created_at
            FROM device_param_analysis_log
            WHERE device_code = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (device_code, limit))
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        for k in ("start_time", "end_time", "created_at"):
            if r.get(k) is not None:
                r[k] = str(r[k])
    return rows
