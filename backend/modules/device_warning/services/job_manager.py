# cython: annotation_typing=False, infer_types=False, language_level=3
import json
import math

from modules.device_warning.ai_analysis.postgres_loader import PostgresDB


def _sanitize(obj):
    """递归将 NaN/Infinity 替换为 None，Timestamp 等转为字符串"""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return obj


def _serialize_records(records: list) -> list:
    """将 DataFrame.to_dict(records) 结果转为可 JSON 序列化的值"""
    return _sanitize(records)


def get_jobs(job_name: str | None = None, status: str | None = None, limit: int = 100):
    """获取任务列表"""
    db = PostgresDB()
    try:
        if not db.connect_with_fallback():
            print("[JobManager] 数据库连接失败")
            return []
        if job_name:
            df = db.get_job_status(job_name, limit=limit)
        else:
            df = db.get_all_job_status(status=status, limit=limit)
        records = df.to_dict(orient="records") if not df.empty else []
        return _serialize_records(records)
    finally:
        db.close()


def get_summary():
    """获取任务统计摘要"""
    db = PostgresDB()
    try:
        if not db.connect_with_fallback():
            print("[JobManager] 数据库连接失败")
            return {}
        result = db.get_job_summary()
        return _sanitize(result)
    finally:
        db.close()


def get_job_history(job_name: str, limit: int = 50):
    """获取指定任务历史"""
    db = PostgresDB()
    try:
        if not db.connect_with_fallback():
            print("[JobManager] 数据库连接失败")
            return []
        df = db.get_job_status(job_name, limit=limit)
        records = df.to_dict(orient="records") if not df.empty else []
        return _serialize_records(records)
    finally:
        db.close()
