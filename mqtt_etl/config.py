# cython: annotation_typing=False, infer_types=False, language_level=3
import os
from dotenv import load_dotenv

load_dotenv()


_WARNED = set()


def _env(name, *old_names, default=""):
    """按 新名 -> 旧名 -> 默认值 取值；命中旧名时打印一次废弃告警。

    与 backend/core/pg_env.py 同一套约定，只是 mqtt_etl 是独立服务、
    不能 import backend，所以这里保留一份最小实现。
    """
    v = os.getenv(name)
    if v not in (None, ""):
        return v
    for old in old_names:
        ov = os.getenv(old)
        if ov not in (None, ""):
            if old not in _WARNED:
                _WARNED.add(old)
                print(f"[config] 环境变量 {old} 已废弃，请改用 {name}（本次仍按 {old} 生效）")
            return ov
    return default


class Config:
    MQTT_BROKER = os.getenv("MQTT_BROKER", "")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
    # 报警点位topic（原有，结构已知，走 AlarmMessageParser -> device_alarm_info）
    MQTT_TOPIC = os.getenv("MQTT_TOPIC", "")
    # 电表能耗点位topic（结构已知，走 EnergyMessageParser -> device_energy_info）
    MQTT_TOPIC_NH = os.getenv("MQTT_TOPIC_NH", "")
    MQTT_USER = os.getenv("MQTT_USER", "")
    MQTT_PASS = os.getenv("MQTT_PASS", "")
    MQTT_QOS = int(os.getenv("MQTT_QOS", "1"))

    # 数据库连接参数：统一用 PG_*，与主应用 backend/core/pg_env.py 保持同名同默认值。
    # DB_* 是本服务早期的旧名，仅为兼容还没改 .env 的 systemd 部署而保留，
    # 命中时会打印废弃告警；新部署一律只配 PG_*。
    DB_HOST = _env("PG_HOST", "DB_HOST", default="127.0.0.1")
    DB_PORT = int(_env("PG_PORT", "DB_PORT", default="5432"))
    DB_NAME = _env("PG_DB", "DB_NAME", default="knowledge_base")
    DB_USER = _env("PG_USER", "DB_USER", default="zxzz")
    DB_PASS = _env("PG_PASSWORD", "DB_PASS", default="")

    BATCH_SIZE = int(os.getenv("BATCH_SIZE", "200"))
    BATCH_TIMEOUT = int(os.getenv("BATCH_TIMEOUT", "5"))

    DEAD_LETTER_DIR = os.getenv("DEAD_LETTER_DIR", "./dead_letter")

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
