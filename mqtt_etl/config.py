# cython: annotation_typing=False, infer_types=False, language_level=3
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    MQTT_BROKER = os.getenv("MQTT_BROKER", "")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
    # 报警点位topic（原有，结构已知，走 AlarmMessageParser -> device_alarm_info）
    MQTT_TOPIC = os.getenv("MQTT_TOPIC", "")
    # 新增topic，结构未知，走 RawMessageParser 原样落库 device_nh_raw，
    # 等拿到服务器上的真实样例后再改造成结构化解析
    MQTT_TOPIC_NH = os.getenv("MQTT_TOPIC_NH", "")
    MQTT_USER = os.getenv("MQTT_USER", "")
    MQTT_PASS = os.getenv("MQTT_PASS", "")
    MQTT_QOS = int(os.getenv("MQTT_QOS", "1"))

    # 数据库连接参数：统一使用 PG_* → DB_* → 默认值
    DB_HOST = os.getenv("PG_HOST") or os.getenv("DB_HOST", "")
    DB_PORT = int(os.getenv("PG_PORT") or os.getenv("DB_PORT", "5432"))
    DB_NAME = os.getenv("PG_DB") or os.getenv("DB_NAME", "knowledge_base")
    DB_USER = os.getenv("PG_USER") or os.getenv("DB_USER", "zxzz")
    DB_PASS = os.getenv("PG_PASSWORD") or os.getenv("DB_PASS", "")

    BATCH_SIZE = int(os.getenv("BATCH_SIZE", "200"))
    BATCH_TIMEOUT = int(os.getenv("BATCH_TIMEOUT", "5"))

    DEAD_LETTER_DIR = os.getenv("DEAD_LETTER_DIR", "./dead_letter")

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
