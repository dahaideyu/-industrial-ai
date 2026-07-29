# cython: annotation_typing=False, infer_types=False, language_level=3
import logging
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values
from datetime import datetime
from typing import List, Tuple
import json
from pathlib import Path

from config import Config

logger = logging.getLogger(__name__)


class DatabaseWriter:
    def __init__(self):
        self.conn = None
        self._connect()
        self.dead_letter_dir = Path(Config.DEAD_LETTER_DIR)
        self.dead_letter_dir.mkdir(exist_ok=True)

    def _connect(self):
        try:
            self.conn = psycopg2.connect(
                host=Config.DB_HOST,
                port=Config.DB_PORT,
                dbname=Config.DB_NAME,
                user=Config.DB_USER,
                password=Config.DB_PASS,
            )
            self.conn.autocommit = False
            logger.info("Database connection established")
            self._ensure_schema()
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            self.conn = None

    def _ensure_schema(self):
        """表不存在时自动建表，并转换为TimescaleDB超表（hypertable）。"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS public.device_alarm_info (
                        device_id varchar(255) NOT NULL,
                        device_status varchar(255) NULL,
                        point_uid int4 NULL,
                        point_id varchar(255) NOT NULL,
                        value_type varchar(255) NULL,
                        point_value int4 NOT NULL,
                        point_value_full numeric(14,4) NULL,
                        point_time timestamp NOT NULL,
                        upload_cycle int4 NULL,
                        south_driver_name varchar(255) NULL,
                        "time" timestamp NULL,
                        load_time timestamp NULL,
                        raw_json jsonb NULL
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS public.device_energy_info (
                        device_id varchar(255) NOT NULL,
                        device_status varchar(255) NULL,
                        point_uid int4 NULL,
                        point_id varchar(255) NOT NULL,
                        point_value numeric(14,4) NULL,
                        point_time timestamp NOT NULL,
                        upload_cycle int4 NULL,
                        south_driver_name varchar(255) NULL,
                        "time" timestamp NULL,
                        load_time timestamp NULL,
                        raw_json jsonb NULL
                    )
                """)

                cur.execute("""
                    SELECT create_hypertable(
                        'public.device_alarm_info', 
                        'point_time', 
                        if_not_exists => TRUE,
                        migrate_data => TRUE,
                        chunk_time_interval => INTERVAL '1 day'
                    )
                """)

                cur.execute("""
                    SELECT create_hypertable(
                        'public.device_energy_info', 
                        'point_time', 
                        if_not_exists => TRUE,
                        migrate_data => TRUE,
                        chunk_time_interval => INTERVAL '1 day'
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_device_alarm_info_device_id
                    ON public.device_alarm_info (device_id, point_time DESC)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_device_alarm_info_point_id
                    ON public.device_alarm_info (point_id, point_time DESC)
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_device_energy_info_device_id
                    ON public.device_energy_info (device_id, point_time DESC)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_device_energy_info_point_id
                    ON public.device_energy_info (point_id, point_time DESC)
                """)

            self.conn.commit()
            logger.info("Schema check passed (device_alarm_info / device_energy_info ensured as hypertables)")
        except Exception as e:
            logger.error(f"Failed to ensure schema: {e}")
            self.conn.rollback()

    def _ensure_connection(self):
        if self.conn is None:
            self._connect()
        else:
            try:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT 1")
            except Exception:
                logger.warning("Database connection lost, reconnecting...")
                self.conn = None
                self._connect()

    def write_alarm_batch(self, records: List[Tuple], raw_json: dict = None):
        if not records:
            return

        self._ensure_connection()
        if self.conn is None:
            self._save_failed_batch(records, raw_json, source="alarm")
            return

        try:
            with self.conn.cursor() as cur:
                load_time = datetime.now()
                sql_query = sql.SQL("""
                    INSERT INTO public.device_alarm_info (
                        device_id, device_status, point_uid, point_id, value_type,
                        point_value, point_value_full, point_time, upload_cycle,
                        south_driver_name, "time", load_time, raw_json
                    ) VALUES %s
                """)

                records_with_loadtime = [
                    rec + (load_time, json.dumps(raw_json) if raw_json else None)
                    for rec in records
                ]

                execute_values(cur, sql_query, records_with_loadtime)
                self.conn.commit()
                logger.info(f"Successfully inserted {len(records)} alarm records")
        except Exception as e:
            logger.error(f"Failed to write alarm batch: {e}")
            if self.conn:
                self.conn.rollback()
            self._save_failed_batch(records, raw_json, source="alarm")

    def write_energy_batch(self, records: List[Tuple], raw_json: dict = None):
        """电表能耗点位批量写入 device_energy_info，写法和 write_alarm_batch 一致。"""
        if not records:
            return

        self._ensure_connection()
        if self.conn is None:
            self._save_failed_batch(records, raw_json, source="energy")
            return

        try:
            with self.conn.cursor() as cur:
                load_time = datetime.now()
                sql_query = sql.SQL("""
                    INSERT INTO public.device_energy_info (
                        device_id, device_status, point_uid, point_id,
                        point_value, point_time, upload_cycle, south_driver_name,
                        "time", load_time, raw_json
                    ) VALUES %s
                """)

                records_with_loadtime = [
                    rec + (load_time, json.dumps(raw_json) if raw_json else None)
                    for rec in records
                ]

                execute_values(cur, sql_query, records_with_loadtime)
                self.conn.commit()
                logger.info(f"Successfully inserted {len(records)} energy records")
        except Exception as e:
            logger.error(f"Failed to write energy batch: {e}")
            if self.conn:
                self.conn.rollback()
            self._save_failed_batch(records, raw_json, source="energy")

    def _save_failed_batch(self, records: List[Tuple], raw_json: dict = None, source: str = "alarm"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = self.dead_letter_dir / f"failed_batch_{source}_{timestamp}.jsonl"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps({
                        "record": rec,
                        "raw_json": raw_json
                    }, ensure_ascii=False, default=str))
                    f.write("\n")
            logger.error(f"Failed batch saved to {filename}")
        except Exception as e:
            logger.critical(f"Failed to save dead letter: {e}")
