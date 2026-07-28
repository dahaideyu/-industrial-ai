# cython: annotation_typing=False, infer_types=False, language_level=3
"""参数画像夜间预生成：对全设备跑 AI 识别(含 LLM)写"建议"画像，让画像页一开即有内容。

只写"建议"(save_suggestions 不覆盖已确认行)。含 LLM 调用，有成本，prod 默认不启用(cron 留空)。
build_profiles 为 async，这里用 asyncio.run 在调度线程里跑(新事件循环)。
"""

import asyncio
from datetime import date
from typing import Any, Dict, Optional

from core.job_logger import JobLogger
from .services import TimescaleDB
from . import param_profile


def run_profile_suggest_job(device_code: Optional[str] = None,
                            use_llm: bool = True) -> Dict[str, Any]:
    """全设备(或单设备)刷新画像"建议"。返回汇总。"""
    jlog = JobLogger(job_type="deviceParamProfileSuggest",
                     report_date=date.today().strftime("%Y-%m-%d"))
    jlog.print_separator()
    jlog.info(f"参数画像夜间预生成开始 device={device_code or '全部'} use_llm={use_llm}")

    db = TimescaleDB()
    if not db.connect():
        jlog.error("TimescaleDB 连接失败")
        return {"ok": False, "error": "db_connect_failed"}

    summary = {"ok": True, "devices": 0, "done": 0, "failed": 0, "suggested": 0}
    try:
        param_profile.ensure_table(db.conn)
        devices = ([{"device_code": device_code}] if device_code else db.get_devices())
        summary["devices"] = len(devices)
        for dev in devices:
            dcode = dev["device_code"]
            try:
                profiles = asyncio.run(
                    param_profile.build_profiles(db, dcode, use_llm=use_llm))
                n = param_profile.save_suggestions(db.conn, dcode, profiles)
                summary["suggested"] += n
                summary["done"] += 1
                jlog.info(f"[{dcode}] 画像建议 {n} 个参数")
            except Exception as e:
                db.conn.rollback()
                summary["failed"] += 1
                jlog.error(f"[{dcode}] 画像预生成失败: {e}", exc_info=True)
        jlog.info(f"完成: {summary['done']}/{summary['devices']} 成功, "
                  f"{summary['failed']} 失败, 建议参数 {summary['suggested']} 个")
        jlog.print_separator()
        return summary
    finally:
        db.close()
