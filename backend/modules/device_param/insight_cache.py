# cython: annotation_typing=False, infer_types=False, language_level=3
"""派生分析的懒加载缓存：派生结果(Cpk/RUL/对标/前兆)算一次存库，当天读缓存秒开。

命中条件：同设备同 kind 的缓存行存在，且 eval_date=今天、params 与本次请求一致。
跨天或换参数即失效→现算并覆盖。沿用 device_diagnosis 的 device×JSONB 缓存模式。
"""

import json
from datetime import date
from typing import Any, Dict, Optional

from psycopg2.extras import RealDictCursor


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_param_insight (
                device_code VARCHAR(64) NOT NULL,
                kind        VARCHAR(24) NOT NULL,
                params      JSONB,
                payload     JSONB,
                eval_date   DATE,
                computed_at TIMESTAMPTZ DEFAULT now(),
                PRIMARY KEY (device_code, kind)
            )
        """)
    conn.commit()


def _norm(params: Optional[Dict[str, Any]]) -> str:
    """参数规范化为可比字符串（键排序），用于命中判断。"""
    return json.dumps(params or {}, ensure_ascii=False, sort_keys=True, default=str)


def read(conn, device_code: str, kind: str,
         params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """命中(当天+同参数)返回 {payload, computed_at}；否则 None。"""
    ensure_table(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""SELECT params, payload, eval_date, computed_at
                       FROM device_param_insight WHERE device_code=%s AND kind=%s""",
                    (device_code, kind))
        r = cur.fetchone()
    if not r or r["eval_date"] != date.today():
        return None
    if _norm(r["params"]) != _norm(params):
        return None
    return {"payload": r["payload"], "computed_at": str(r["computed_at"])}


def write(conn, device_code: str, kind: str,
          params: Optional[Dict[str, Any]], payload: Any) -> None:
    """覆盖写入(eval_date=今天)。"""
    ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO device_param_insight
              (device_code, kind, params, payload, eval_date, computed_at)
            VALUES (%s, %s, %s::jsonb, %s::jsonb, CURRENT_DATE, now())
            ON CONFLICT (device_code, kind) DO UPDATE SET
              params=EXCLUDED.params, payload=EXCLUDED.payload,
              eval_date=EXCLUDED.eval_date, computed_at=now()
        """, (device_code, kind,
              json.dumps(params or {}, ensure_ascii=False, default=str),
              json.dumps(payload, ensure_ascii=False, default=str)))
    conn.commit()
