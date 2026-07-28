# cython: annotation_typing=False, infer_types=False, language_level=3
import logging
import json
from typing import List, Tuple, Optional
from datetime import datetime
from pathlib import Path

from config import Config

logger = logging.getLogger(__name__)


class AlarmMessageParser:
    """解析 Config.MQTT_TOPIC（报警点位）的消息，结构固定，展平进 device_alarm_info。"""

    def __init__(self):
        self.dead_letter_dir = Path(Config.DEAD_LETTER_DIR)
        self.dead_letter_dir.mkdir(exist_ok=True)

    def parse(self, payload: bytes, topic: str = None) -> Tuple[List[Tuple], Optional[dict]]:
        try:
            msg_str = payload.decode("utf-8")
        except UnicodeDecodeError as e:
            logger.error(f"Failed to decode payload: {e}")
            self._save_malformed(payload, "decode_error")
            return [], None

        try:
            data = json.loads(msg_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            self._save_malformed(msg_str, "json_error")
            return [], None

        records = []
        msg_time = data.get("time")

        for device in data.get("devices", []):
            device_id = device.get("device_id")
            device_status = device.get("device_status")
            south_driver_name = device.get("south_driver_name")

            for point in device.get("points", []):
                try:
                    record = self._build_record(
                        device_id=device_id,
                        device_status=device_status,
                        south_driver_name=south_driver_name,
                        point=point,
                        msg_time=msg_time
                    )
                    records.append(record)
                except Exception as e:
                    logger.warning(f"Failed to build record for point: {e}")

        return records, data

    def _build_record(
        self,
        device_id: str,
        device_status: str,
        south_driver_name: str,
        point: dict,
        msg_time: str
    ) -> Tuple:
        point_uid = int(point["point_uid"]) if point.get("point_uid") else None
        point_id = point["point_id"]
        value_type = point.get("value_type")

        point_value_str = point["point_value"]
        try:
            point_value = int(float(point_value_str))
        except (ValueError, TypeError):
            point_value = 0

        try:
            point_value_full = float(point_value_str)
        except (ValueError, TypeError):
            point_value_full = None

        point_time = self._parse_timestamp(point.get("point_time"))
        upload_cycle = int(point["upload_cycle"]) if point.get("upload_cycle") else None
        time = self._parse_timestamp(msg_time)

        return (
            device_id,
            device_status,
            point_uid,
            point_id,
            value_type,
            point_value,
            point_value_full,
            point_time,
            upload_cycle,
            south_driver_name,
            time,
        )

    def _parse_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        if not ts_str:
            return None
        try:
            return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            try:
                return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                logger.warning(f"Failed to parse timestamp: {ts_str}")
                return None

    def _save_malformed(self, data, error_type: str):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = self.dead_letter_dir / f"malformed_{error_type}_{timestamp}.log"
        try:
            mode = "wb" if isinstance(data, bytes) else "w"
            encoding = None if isinstance(data, bytes) else "utf-8"
            with open(filename, mode, encoding=encoding) as f:
                f.write(data)
            logger.error(f"Malformed message saved to {filename}")
        except Exception as e:
            logger.critical(f"Failed to save malformed message: {e}")


class EnergyMessageParser:
    """解析 Config.MQTT_TOPIC_NH（电表能耗点位，结构已确认）的消息，展平进 device_energy_info。

    报文结构和 AlarmMessageParser 解析的报警点位完全一致（devices[].points[]），
    只是没有 value_type。31 个 point_id（ene_ua/ene_pt/...）的中文名对照见
    docs/江西设备AI信息表.xlsx「能耗参数」sheet。

    与 AlarmMessageParser 的关键差异：point_value 这里是电压/电流/功率/功率因数等
    连续量（如 220.35、0.98），不能像报警点位那样截断成整数，所以按 float 存，
    解析失败存 None 而不是 0（避免和真实的 0 值混淆）。
    """

    def __init__(self):
        self.dead_letter_dir = Path(Config.DEAD_LETTER_DIR)
        self.dead_letter_dir.mkdir(exist_ok=True)

    def parse(self, payload: bytes, topic: str = None) -> Tuple[List[Tuple], Optional[dict]]:
        try:
            msg_str = payload.decode("utf-8")
        except UnicodeDecodeError as e:
            logger.error(f"Failed to decode payload: {e}")
            self._save_malformed(payload, "decode_error")
            return [], None

        try:
            data = json.loads(msg_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            self._save_malformed(msg_str, "json_error")
            return [], None

        records = []
        msg_time = data.get("time")

        for device in data.get("devices", []):
            device_id = device.get("device_id")
            device_status = device.get("device_status")
            south_driver_name = device.get("south_driver_name")

            for point in device.get("points", []):
                try:
                    record = self._build_record(
                        device_id=device_id,
                        device_status=device_status,
                        south_driver_name=south_driver_name,
                        point=point,
                        msg_time=msg_time
                    )
                    records.append(record)
                except Exception as e:
                    logger.warning(f"Failed to build energy record for point: {e}")

        return records, data

    def _build_record(
        self,
        device_id: str,
        device_status: str,
        south_driver_name: str,
        point: dict,
        msg_time: str
    ) -> Tuple:
        point_uid = int(point["point_uid"]) if point.get("point_uid") else None
        point_id = point["point_id"]

        point_value_str = point["point_value"]
        try:
            point_value = float(point_value_str)
        except (ValueError, TypeError):
            point_value = None

        point_time = self._parse_timestamp(point.get("point_time"))
        upload_cycle = int(point["upload_cycle"]) if point.get("upload_cycle") else None
        time = self._parse_timestamp(msg_time)

        return (
            device_id,
            device_status,
            point_uid,
            point_id,
            point_value,
            point_time,
            upload_cycle,
            south_driver_name,
            time,
        )

    def _parse_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        if not ts_str:
            return None
        try:
            return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            try:
                return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                logger.warning(f"Failed to parse timestamp: {ts_str}")
                return None

    def _save_malformed(self, data, error_type: str):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = self.dead_letter_dir / f"energy_malformed_{error_type}_{timestamp}.log"
        try:
            mode = "wb" if isinstance(data, bytes) else "w"
            encoding = None if isinstance(data, bytes) else "utf-8"
            with open(filename, mode, encoding=encoding) as f:
                f.write(data)
            logger.error(f"Malformed message saved to {filename}")
        except Exception as e:
            logger.critical(f"Failed to save malformed message: {e}")


class RawMessageParser:
    """
    通用原样落库解析器，用于结构还未知的topic（目前是 Config.MQTT_TOPIC_NH）。

    不假设任何 JSON 结构，能解析成 JSON 就整体存进 raw_json(jsonb)，解析不了
    就存进 raw_text，保证不丢数据。等拿到服务器上跑出来的真实样例后，
    再针对具体结构改造成和 AlarmMessageParser 一样的结构化解析 + 专属数据表。
    """

    def __init__(self):
        self.dead_letter_dir = Path(Config.DEAD_LETTER_DIR)
        self.dead_letter_dir.mkdir(exist_ok=True)

    def parse(self, payload: bytes, topic: str = None) -> Tuple[List[Tuple], Optional[dict]]:
        received_at = datetime.now()

        try:
            msg_str = payload.decode("utf-8")
        except UnicodeDecodeError as e:
            logger.error(f"Failed to decode payload on topic {topic}: {e}")
            self._save_malformed(payload, "decode_error")
            return [], None

        raw_json: Optional[dict] = None
        raw_text: Optional[str] = None
        try:
            raw_json = json.loads(msg_str)
        except json.JSONDecodeError:
            raw_text = msg_str
            logger.warning(f"Message on topic {topic} is not valid JSON, storing as raw text")

        record = (
            topic,
            json.dumps(raw_json, ensure_ascii=False) if raw_json is not None else None,
            raw_text,
            received_at,
        )
        return [record], raw_json

    def _save_malformed(self, data, error_type: str):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = self.dead_letter_dir / f"nh_malformed_{error_type}_{timestamp}.log"
        try:
            mode = "wb" if isinstance(data, bytes) else "w"
            encoding = None if isinstance(data, bytes) else "utf-8"
            with open(filename, mode, encoding=encoding) as f:
                f.write(data)
            logger.error(f"Malformed message saved to {filename}")
        except Exception as e:
            logger.critical(f"Failed to save malformed message: {e}")
