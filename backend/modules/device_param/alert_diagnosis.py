# cython: annotation_typing=False, infer_types=False, language_level=3
"""分阶段漂移报警的"知识库诊断"：用报警事实 + RAGFlow 知识库 → 生成结合知识库的分析，落库缓存。

每条报警/正常读数(device×metric×stage×eval_date×baseline_days)都生成一段结合知识库的分析，
存 device_param_alert_diagnosis，页面/日报只读。warning/critical 生成"问题判断/可能原因/
排查建议"；info(正常范围内，未触发预警)生成"当前状态/相关知识"信息汇总，不是诊断问题
（本来就没问题），只是把知识库里的相关背景信息带出来方便日常查看。知识库走 RAGFlow 设备
文档助手(env RAGFLOW_DOC_ASSISTANT_ID，可用 DEVICE_PARAM_ALERT_KB_CHAT_ID 覆盖)；助手本身
做"检索+LLM"，返回的 answer 即"结合知识库的分析"，无需再单独调 LLM。
"""

import os
import json
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor

from .stage_analysis import db_device_name

_DIR = {"up": "逐渐升高", "down": "逐渐降低", "flat": "基本平稳"}


def ensure_table(conn) -> None:
    """建知识库诊断表（幂等，沿用项目内联 CREATE IF NOT EXISTS 风格）。"""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_param_alert_diagnosis (
                device_code   VARCHAR(64)  NOT NULL,
                metric        VARCHAR(128) NOT NULL,
                stage         SMALLINT,
                eval_date     DATE         NOT NULL,
                baseline_days SMALLINT     NOT NULL,
                display_name  VARCHAR(256),
                severity      VARCHAR(12),
                direction     VARCHAR(8),
                problem       TEXT,
                kb_evidence   TEXT,
                kb_refs       JSONB,
                ok            BOOLEAN     DEFAULT TRUE,
                created_at    TIMESTAMPTZ DEFAULT now()
            )
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_device_param_alert_diagnosis
            ON device_param_alert_diagnosis
               (device_code, metric, (COALESCE(stage, -1)), eval_date, baseline_days)
        """)
    conn.commit()


_PROBLEM_SEVERITIES = ("warning", "critical")


def build_question(alert: Dict[str, Any], dev_name: str) -> str:
    """把报警事实组成给知识库助手的中文提问（含趋势量化 + 作答要求）。

    warning/critical：按"有问题"提问，走根因排查框架（原有逻辑不变）。
    info/其余（未触发预警，属正常范围）：按"无问题"提问，走知识库信息汇总框架——
    不能问"这是什么问题"（没问题），改问该参数相关的背景知识，方便日常查看。
    """
    disp = alert.get("display_name") or alert.get("metric")
    stage = alert.get("stage")
    stage_txt = f"第 {int(stage)} 阶段内" if stage is not None else "整机运行中"
    direction = _DIR.get(alert.get("direction"), alert.get("direction") or "变化")
    severity = alert.get("severity")

    facts: List[str] = [
        f"设备「{dev_name}」的参数「{disp}」在{stage_txt}，"
        f"近 {alert.get('baseline_days')} 天呈{direction}的趋势。"
    ]
    if alert.get("change_pct") is not None:
        facts.append(f"相对基线变化 {alert['change_pct']}%；")
    if alert.get("robust_z") is not None:
        facts.append(f"稳健 z={alert['robust_z']}（约 {abs(float(alert['robust_z'])):.1f}σ）；")
    if alert.get("sen_slope") is not None:
        facts.append(f"Sen 斜率 {alert['sen_slope']}/天；")
    facts.append(f"严重度 {severity}。")
    if alert.get("note"):
        facts.append(f"备注：{alert['note']}。")

    if severity in _PROBLEM_SEVERITIES:
        ask = (
            f"\n请结合该设备的技术文档/工艺资料，判断该参数{direction}最可能是什么问题"
            "（根因），会对工艺、质量或设备造成什么影响，应如何排查与处理。"
            "请分『问题判断』『可能原因』『排查与建议』三段简要作答，并标注来源文档名称。"
        )
    else:
        ask = (
            "\n目前该参数变化幅度尚在正常范围内，未触发预警，并非需要处理的问题。"
            "请结合该设备的技术文档/工艺资料，简要给出这个参数相关的背景信息汇总"
            "（正常范围、主要影响因素、需要留意的临界值等），供日常查看参考。"
            "请分『当前状态』『相关知识』两段简要作答，并标注来源文档名称。"
        )

    return "".join(facts) + ask


def _kb_chat(question: str) -> tuple:
    """同步调 RAGFlow 设备文档知识库助手，返回 (answer, refs_dict, err)。"""
    chat_id = (os.getenv("DEVICE_PARAM_ALERT_KB_CHAT_ID")
               or os.getenv("RAGFLOW_DOC_ASSISTANT_ID"))
    if not chat_id:
        return None, None, "未配置知识库助手(RAGFLOW_DOC_ASSISTANT_ID)"
    try:
        try:
            from backend.services.agentic_qa.ragflow.client import RAGFlowClient
        except ImportError:
            from services.agentic_qa.ragflow.client import RAGFlowClient
        client = RAGFlowClient()
        client.chat_id = chat_id          # chat_sync 用 self.chat_id
        res = client.chat_sync(question)
    except Exception as e:
        return None, None, f"知识库调用异常: {e}"
    if not res.get("success"):
        return None, None, res.get("error") or "知识库调用失败"
    return res.get("answer"), res.get("references"), None


def _summarize_refs(refs: Optional[Dict[str, Any]]) -> Optional[str]:
    """从 RAGFlow references 提来源文档名（命中证据，给页面展示）。"""
    if not refs or not isinstance(refs, dict):
        return None
    names = [a.get("doc_name") for a in (refs.get("doc_aggs") or []) if a.get("doc_name")]
    if not names:
        names = [c.get("document_keyword") or c.get("doc_name")
                 for c in (refs.get("chunks") or [])
                 if (c.get("document_keyword") or c.get("doc_name"))]
    names = list(dict.fromkeys([n for n in names if n]))
    return "；".join(names[:8]) if names else None


_COLS = ["device_code", "metric", "stage", "eval_date", "baseline_days", "display_name",
         "severity", "direction", "problem", "kb_evidence", "kb_refs", "ok"]


def _upsert(conn, row: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO device_param_alert_diagnosis
              (device_code, metric, stage, eval_date, baseline_days, display_name,
               severity, direction, problem, kb_evidence, kb_refs, ok, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s, now())
            ON CONFLICT (device_code, metric, (COALESCE(stage, -1)), eval_date, baseline_days)
            DO UPDATE SET display_name=EXCLUDED.display_name, severity=EXCLUDED.severity,
              direction=EXCLUDED.direction, problem=EXCLUDED.problem,
              kb_evidence=EXCLUDED.kb_evidence, kb_refs=EXCLUDED.kb_refs,
              ok=EXCLUDED.ok, created_at=now()
        """, (row["device_code"], row["metric"], row.get("stage"), row["eval_date"],
              row["baseline_days"], row.get("display_name"), row.get("severity"),
              row.get("direction"), row.get("problem"), row.get("kb_evidence"),
              json.dumps(row["kb_refs"], ensure_ascii=False) if row.get("kb_refs") else None,
              row.get("ok", True)))
    conn.commit()


def diagnose_alert(db, alert: Dict[str, Any]) -> Dict[str, Any]:
    """对单条报警生成知识库诊断并 upsert。alert 需含
    device_code/metric/stage/eval_date/baseline_days(+趋势字段)。返回保存的诊断 dict。"""
    ensure_table(db.conn)
    dev_name = db_device_name(db, alert["device_code"])
    answer, refs, err = _kb_chat(build_question(alert, dev_name))
    if err:
        problem, kb_evidence, kb_refs, ok = f"（知识库诊断未生成：{err}）", None, None, False
    else:
        problem = answer or "（知识库无相关返回）"
        kb_evidence = _summarize_refs(refs)
        kb_refs = refs
        ok = bool(answer)

    row = {
        "device_code": alert["device_code"], "metric": alert["metric"],
        "stage": (int(alert["stage"]) if alert.get("stage") is not None else None),
        "eval_date": alert["eval_date"], "baseline_days": int(alert["baseline_days"]),
        "display_name": alert.get("display_name"), "severity": alert.get("severity"),
        "direction": alert.get("direction"), "problem": problem,
        "kb_evidence": kb_evidence, "kb_refs": kb_refs, "ok": ok,
    }
    _upsert(db.conn, row)
    return _clean(row)


def _clean(r: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(r)
    out["eval_date"] = str(out.get("eval_date"))
    out.pop("kb_refs", None)   # 详细引用不回传页面，只回 kb_evidence 文本
    return out


def read_for_alert(conn, device_code: str, metric: str, stage: Optional[int],
                   eval_date, baseline_days: int) -> Optional[Dict[str, Any]]:
    """读单条报警的已存诊断（无则 None）。"""
    ensure_table(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT device_code, metric, stage, eval_date, baseline_days, display_name,
                   severity, direction, problem, kb_evidence, ok, created_at
            FROM device_param_alert_diagnosis
            WHERE device_code=%s AND metric=%s AND COALESCE(stage,-1)=%s
              AND eval_date=%s AND baseline_days=%s
        """, (device_code, metric, -1 if stage is None else int(stage),
              eval_date, baseline_days))
        r = cur.fetchone()
    if not r:
        return None
    r = dict(r)
    r["eval_date"] = str(r["eval_date"])
    r["created_at"] = str(r["created_at"])
    return r


def read_map_for_device(conn, device_code: str, eval_date,
                        baseline_days: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
    """该设备某评估日的诊断映射 {f"{metric}|{stage}": 行}，供列表批量标记/展示。"""
    ensure_table(conn)
    conds = ["device_code=%s", "eval_date=%s"]
    params: List[Any] = [device_code, eval_date]
    if baseline_days is not None:
        conds.append("baseline_days=%s")
        params.append(baseline_days)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"""
            SELECT metric, stage, severity, direction, problem, kb_evidence, ok, created_at
            FROM device_param_alert_diagnosis
            WHERE {" AND ".join(conds)}
        """, tuple(params))
        out: Dict[str, Dict[str, Any]] = {}
        for r in cur.fetchall():
            r = dict(r)
            r["created_at"] = str(r["created_at"])
            key = f"{r['metric']}|{'' if r['stage'] is None else int(r['stage'])}"
            out[key] = r
    return out
