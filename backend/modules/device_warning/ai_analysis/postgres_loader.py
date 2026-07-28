# cython: annotation_typing=False, infer_types=False, language_level=3
"""
PostgreSQL 数据库连接模块 - 支持连接池复用
"""
import os
import sys
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
import pandas as pd
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import dotenv

dotenv.load_dotenv()


class PostgresPool:
    """PostgreSQL 连接池"""

    _instance = None
    _connection_pool = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._connection_pool is None:
            self._init_pool()

    def _init_pool(self):
        """初始化连接池"""
        host = os.getenv("PG_HOST")
        port = os.getenv("PG_PORT", "5432")
        dbname = os.getenv("PG_DB", "knowledge_base")
        user = os.getenv("PG_USER", "postgres")
        password = os.getenv("PG_PASSWORD")

        try:
            self._connection_pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                host=host,
                port=port,
                database=dbname,
                user=user,
                password=password
            )
            print(f"[PostgreSQL] 连接池已创建: {host}:{port}")
        except Exception as e:
            print(f"[PostgreSQL] 连接池创建失败: {e}")
            self._connection_pool = None

    def get_connection(self):
        """获取连接"""
        if self._connection_pool is None:
            self._init_pool()
        if self._connection_pool:
            return self._connection_pool.getconn()
        return None

    def release_connection(self, conn):
        """释放连接回池"""
        if self._connection_pool and conn:
            self._connection_pool.putconn(conn)

    def close_all(self):
        """关闭所有连接"""
        if self._connection_pool:
            self._connection_pool.closeall()
            self._connection_pool = None


class PostgresDB:
    """PostgreSQL 操作类 - 使用连接池"""

    def __init__(self):
        self.pool = PostgresPool()
        self.conn = None

    def connect(self) -> bool:
        """获取连接"""
        self.conn = self.pool.get_connection()
        return self.conn is not None

    def connect_with_fallback(self) -> bool:
        """尝试主连接，失败则用备用"""
        if self.connect():
            return True

        # 尝试备用主机
        fallback_host = os.getenv("PG_FALLBACK_HOST")
        if fallback_host:
            print(f"[PostgreSQL] 尝试备用主机: {fallback_host}")
            host = os.getenv("PG_HOST")
            os.environ["PG_HOST"] = fallback_host
            self.pool._init_pool()
            return self.connect()
        return False

    def close(self):
        """释放连接"""
        if self.conn:
            self.pool.release_connection(self.conn)
            self.conn = None

    def get_tables(self) -> List[Dict[str, Any]]:
        """获取所有表"""
        if not self.conn:
            return []

        query = """
            SELECT table_name, table_schema
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query)
            return cursor.fetchall()

    def get_table_structure(self, table_name: str) -> List[Dict[str, Any]]:
        """获取表结构"""
        if not self.conn:
            return []

        query = """
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_name = %s AND table_schema = 'public'
            ORDER BY ordinal_position;
        """
        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, (table_name,))
            return cursor.fetchall()

    def get_table_data(self, table_name: str, limit: int = 100) -> pd.DataFrame:
        """获取表数据"""
        if not self.conn:
            return pd.DataFrame()

        query = f"SELECT * FROM {table_name} LIMIT %s"
        return pd.read_sql(query, self.conn, params=(limit,))

    def query(self, sql: str, params: tuple = None) -> pd.DataFrame:
        """执行查询"""
        if not self.conn:
            return pd.DataFrame()
        return pd.read_sql(sql, self.conn, params=params)

    def execute(self, sql: str, params: tuple = None) -> bool:
        """执行SQL"""
        if not self.conn:
            return False
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, params)
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            print(f"[PostgreSQL] 执行失败: {e}")
            return False

    def execute_returning(self, sql: str, params: tuple = None) -> Any:
        """执行SQL并返回ID"""
        if not self.conn:
            return None
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, params)
                self.conn.commit()
                return cursor.lastrowid
        except Exception as e:
            self.conn.rollback()
            print(f"[PostgreSQL] 执行失败: {e}")
            return None

    def create_job_tables(self):
        """创建Job相关表"""
        if not self.conn:
            return False

        # Job运行记录表
        create_job_run = """
        CREATE TABLE IF NOT EXISTS analysis_job_run (
            id SERIAL PRIMARY KEY,
            job_name VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP,
            duration_seconds INTEGER,
            result_summary JSONB,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        # Job日志表
        create_job_log = """
        CREATE TABLE IF NOT EXISTS analysis_job_log (
            id SERIAL PRIMARY KEY,
            job_run_id INTEGER REFERENCES analysis_job_run(id),
            log_level VARCHAR(20) NOT NULL,
            message TEXT NOT NULL,
            details JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        # Job配置表
        create_job_config = """
        CREATE TABLE IF NOT EXISTS analysis_job_config (
            id SERIAL PRIMARY KEY,
            job_name VARCHAR(50) UNIQUE NOT NULL,
            display_name VARCHAR(100) NOT NULL,
            description TEXT,
            interval_seconds INTEGER NOT NULL DEFAULT 3600,
            enabled BOOLEAN DEFAULT TRUE,
            last_manual_trigger TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        # 初始化默认配置
        init_job_config = """
        INSERT INTO analysis_job_config (job_name, display_name, description, interval_seconds) VALUES
            ('anomaly_detection', '异常检测', '实时监控设备参数异常，预测即将触发的报警', 300),
            ('health_check', '健康看板', '综合评估设备整体健康状态，输出0-100分的健康指数', 3600),
            ('fault_prediction', '故障预测', '基于参数变化模式识别潜在故障风险，预测故障发生时间', 14400),
            ('energy_analysis', '能耗分析', '分析设备能耗特征，识别节能潜力，提供优化建议', 86400)
        ON CONFLICT (job_name) DO NOTHING;
        """

        # 创建索引
        create_index = """
        CREATE INDEX IF NOT EXISTS idx_job_run_name_status
        ON analysis_job_run(job_name, status);
        CREATE INDEX IF NOT EXISTS idx_job_run_start_time
        ON analysis_job_run(start_time);
        CREATE INDEX IF NOT EXISTS idx_job_log_job_run_id
        ON analysis_job_log(job_run_id);
        """

        try:
            with self.conn.cursor() as cursor:
                cursor.execute(create_job_run)
                cursor.execute(create_job_log)
                cursor.execute(create_job_config)
                cursor.execute(init_job_config)
                cursor.execute(create_index)
                self.conn.commit()
                print("[PostgreSQL] Job表已创建")
                return True
        except Exception as e:
            self.conn.rollback()
            print(f"[PostgreSQL] 创建表失败: {e}")
            return False

    def get_job_config(self, job_name: str = None) -> pd.DataFrame:
        """获取Job配置"""
        if not self.conn:
            return pd.DataFrame()

        if job_name:
            sql = """
                SELECT job_name, display_name, description, interval_seconds,
                       enabled, last_manual_trigger, updated_at
                FROM analysis_job_config
                WHERE job_name = %s
            """
            return pd.read_sql(sql, self.conn, params=(job_name,))
        else:
            sql = """
                SELECT job_name, display_name, description, interval_seconds,
                       enabled, last_manual_trigger, updated_at
                FROM analysis_job_config
                ORDER BY id
            """
            return pd.read_sql(sql, self.conn)

    def update_job_config(self, job_name: str, interval_seconds: int = None,
                          enabled: bool = None) -> bool:
        """更新Job配置"""
        if not self.conn:
            return False

        updates = []
        params = []

        if interval_seconds is not None:
            updates.append("interval_seconds = %s")
            params.append(interval_seconds)
        if enabled is not None:
            updates.append("enabled = %s")
            params.append(enabled)

        if not updates:
            return False

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(job_name)

        sql = """
            UPDATE analysis_job_config
            SET {}
            WHERE job_name = %s
        """.format(', '.join(updates))
        return self.execute(sql, tuple(params))

    def record_manual_trigger(self, job_name: str) -> bool:
        """记录手动触发时间"""
        if not self.conn:
            return False

        sql = """
            UPDATE analysis_job_config
            SET last_manual_trigger = CURRENT_TIMESTAMP
            WHERE job_name = %s
        """
        return self.execute(sql, (job_name,))

    def get_latest_run_per_job(self) -> pd.DataFrame:
        """获取每个Job的最近一次运行"""
        if not self.conn:
            return pd.DataFrame()

        sql = """
            SELECT DISTINCT ON (job_name)
                   id, job_name, status, start_time, end_time,
                   duration_seconds, result_summary, error_message
            FROM analysis_job_run
            ORDER BY job_name, start_time DESC
        """
        return pd.read_sql(sql, self.conn)

    def start_job(self, job_name: str) -> Optional[int]:
        """记录Job开始"""
        if not self.conn:
            return None

        sql = """
            INSERT INTO analysis_job_run (job_name, status, start_time)
            VALUES (%s, 'running', CURRENT_TIMESTAMP)
            RETURNING id;
        """
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, (job_name,))
                self.conn.commit()
                return cursor.fetchone()[0]
        except Exception as e:
            self.conn.rollback()
            print(f"[PostgreSQL] 记录Job失败: {e}")
            return None

    def end_job(self, job_run_id: int, status: str = 'success',
              result_summary: dict = None, error_message: str = None):
        """记录Job结束"""
        if not self.conn:
            return False

        sql = """
            UPDATE analysis_job_run
            SET status = %s,
                end_time = CURRENT_TIMESTAMP,
                duration_seconds = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - start_time))::INTEGER,
                result_summary = %s,
                error_message = %s
            WHERE id = %s;
        """
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, (status, json.dumps(result_summary), error_message, job_run_id))
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            print(f"[PostgreSQL] 更新Job失败: {e}")
            return False

    def add_job_log(self, job_run_id: int, level: str, message: str,
                  details: dict = None):
        """添加Job日志"""
        if not self.conn:
            return False

        sql = """
            INSERT INTO analysis_job_log (job_run_id, log_level, message, details)
            VALUES (%s, %s, %s, %s);
        """
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, (job_run_id, level, message, json.dumps(details)))
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            return False

    def get_job_status(self, job_name: str, limit: int = 10) -> pd.DataFrame:
        """获取Job运行状态"""
        if not self.conn:
            return pd.DataFrame()

        sql = """
            SELECT id, job_name, status, start_time, end_time,
                   duration_seconds, error_message
            FROM analysis_job_run
            WHERE job_name = %s
            ORDER BY start_time DESC
            LIMIT %s;
        """
        return pd.read_sql(sql, self.conn, params=(job_name, limit))

    def get_all_job_status(self, status: str = None, limit: int = 100) -> pd.DataFrame:
        """获取所有Job运行状态"""
        if not self.conn:
            return pd.DataFrame()

        if status:
            sql = """
                SELECT id, job_name, status, start_time, end_time,
                       duration_seconds, error_message
                FROM analysis_job_run
                WHERE status = %s
                ORDER BY start_time DESC
                LIMIT %s;
            """
            return pd.read_sql(sql, self.conn, params=(status, limit))
        else:
            sql = """
                SELECT id, job_name, status, start_time, end_time,
                       duration_seconds, error_message
                FROM analysis_job_run
                ORDER BY start_time DESC
                LIMIT %s;
            """
            return pd.read_sql(sql, self.conn, params=(limit,))

    def get_job_summary(self) -> dict:
        """获取Job统计摘要"""
        if not self.conn:
            return {}

        sql = """
            SELECT status, COUNT(*) as count
            FROM analysis_job_run
            GROUP BY status;
        """
        df = pd.read_sql(sql, self.conn)
        return {"total": len(df), "statuses": df.to_dict("records") if len(df) > 0 else []}

    def get_job_logs(self, job_run_id: int) -> pd.DataFrame:
        """获取Job日志"""
        if not self.conn:
            return pd.DataFrame()

        sql = """
            SELECT log_level, message, details, created_at
            FROM analysis_job_log
            WHERE job_run_id = %s
            ORDER BY created_at;
        """
        return pd.read_sql(sql, self.conn, params=(job_run_id,))

    # ==================== 报警记录查询 ====================

    def get_alarm_records(
        self,
        device_id: str = None,
        alarm_name: str = None,
        start_time: str = None,
        end_time: str = None,
        only_active: bool = False,
        page: int = 1,
        page_size: int = 50
    ) -> dict:
        """
        分页查询报警记录

        Args:
            device_id: 设备ID
            alarm_name: 报警名称（模糊搜索）
            start_time: 开始时间
            end_time: 结束时间
            only_active: 只查询活跃报警 (point_value = 1)
            page: 页码 (从1开始)
            page_size: 每页数量

        Returns:
            {
                "total": 总数,
                "page": 当前页,
                "page_size": 每页数量,
                "total_pages": 总页数,
                "items": [报警记录列表]
            }
        """
        if not self.conn:
            return {"total": 0, "page": page, "page_size": page_size, "total_pages": 0, "items": []}

        # 构建查询条件
        conditions = []
        params = []

        if device_id:
            conditions.append("a.device_id = %s")
            params.append(device_id)

        if start_time:
            conditions.append("a.point_time >= %s")
            params.append(start_time)

        if end_time:
            conditions.append("a.point_time <= %s")
            params.append(end_time)

        if only_active:
            conditions.append("a.point_value = 1")

        if alarm_name:
            conditions.append("a.point_id ILIKE %s")
            params.append(f"%{alarm_name}%")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 查询总数
        count_sql = """
            SELECT COUNT(*) as total
            FROM device_alarm_info a
            WHERE {}
        """.format(where_clause)

        try:
            with self.conn.cursor() as cursor:
                cursor.execute(count_sql, tuple(params))
                total = cursor.fetchone()[0]
        except Exception as e:
            print(f"[PostgreSQL] 查询报警总数失败: {e}")
            return {"total": 0, "page": page, "page_size": page_size, "total_pages": 0, "items": []}

        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        offset = (page - 1) * page_size

        # 查询数据
        data_sql = """
            SELECT
                a.device_id,
                d.device_name,
                a.point_id,
                a.point_value,
                a.point_time,
                a.device_status,
                a.value_type
            FROM device_alarm_info a
            LEFT JOIN device_info d ON a.device_id = d.device_id
            WHERE {}
            ORDER BY a.point_time DESC
            LIMIT %s OFFSET %s
        """.format(where_clause)

        params.extend([page_size, offset])

        try:
            df = pd.read_sql(data_sql, self.conn, params=tuple(params))
            items = df.to_dict('records')

            # 处理时间格式
            for item in items:
                if item.get('point_time') and hasattr(item['point_time'], 'isoformat'):
                    item['point_time'] = item['point_time'].isoformat()

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "items": items
            }
        except Exception as e:
            print(f"[PostgreSQL] 查询报警记录失败: {e}")
            return {"total": 0, "page": page, "page_size": page_size, "total_pages": 0, "items": []}

    def get_alarm_statistics(
        self,
        device_id: str = None,
        start_time: str = None,
        end_time: str = None
    ) -> dict:
        """
        获取报警统计信息

        Returns:
            {
                "total": 总报警数,
                "active": 活跃报警数,
                "by_device": [{"device_id": x, "device_name": x, "count": x}],
                "by_type": [{"point_id": x, "count": x}],
                "hourly_trend": [{"hour": x, "count": x}]
            }
        """
        if not self.conn:
            return {"total": 0, "active": 0, "by_device": [], "by_type": [], "hourly_trend": []}

        conditions = []
        params = []

        if device_id:
            conditions.append("a.device_id = %s")
            params.append(device_id)

        if start_time:
            conditions.append("a.point_time >= %s")
            params.append(start_time)

        if end_time:
            conditions.append("a.point_time <= %s")
            params.append(end_time)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        result = {
            "total": 0,
            "active": 0,
            "by_device": [],
            "by_type": [],
            "hourly_trend": []
        }

        try:
            # 总数和活跃数
            count_sql = """
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE a.point_value = 1) as active
                FROM device_alarm_info a
                WHERE {}
            """.format(where_clause)
            with self.conn.cursor() as cursor:
                cursor.execute(count_sql, tuple(params))
                row = cursor.fetchone()
                result["total"] = row[0]
                result["active"] = row[1]

            # 按设备统计
            device_sql = """
                SELECT a.device_id, d.device_name, COUNT(*) as count
                FROM device_alarm_info a
                LEFT JOIN device_info d ON a.device_id = d.device_id
                WHERE {}
                GROUP BY a.device_id, d.device_name
                ORDER BY count DESC
                LIMIT 10
            """.format(where_clause)
            df = pd.read_sql(device_sql, self.conn, params=tuple(params))
            result["by_device"] = df.to_dict('records')

            # 按类型统计
            type_sql = """
                SELECT point_id, COUNT(*) as count
                FROM device_alarm_info a
                WHERE {} AND point_value = 1
                GROUP BY point_id
                ORDER BY count DESC
                LIMIT 10
            """.format(where_clause)
            df = pd.read_sql(type_sql, self.conn, params=tuple(params))
            result["by_type"] = df.to_dict('records')

            # 小时趋势
            trend_sql = """
                SELECT EXTRACT(HOUR FROM point_time) as hour, COUNT(*) as count
                FROM device_alarm_info a
                WHERE {} AND point_value = 1
                GROUP BY EXTRACT(HOUR FROM point_time)
                ORDER BY hour
            """.format(where_clause)
            df = pd.read_sql(trend_sql, self.conn, params=tuple(params))
            result["hourly_trend"] = df.to_dict('records')

        except Exception as e:
            print(f"[PostgreSQL] 获取报警统计失败: {e}")

        return result

    def get_device_list_with_alarms(self) -> list:
        """获取有报警记录的设备列表"""
        if not self.conn:
            return []

        sql = """
            SELECT DISTINCT
                a.device_id,
                d.device_name,
                COUNT(*) as alarm_count,
                COUNT(*) FILTER (WHERE a.point_value = 1) as active_count,
                MAX(a.point_time) as last_alarm_time
            FROM device_alarm_info a
            LEFT JOIN device_info d ON a.device_id = d.device_id
            GROUP BY a.device_id, d.device_name
            ORDER BY alarm_count DESC
        """

        try:
            df = pd.read_sql(sql, self.conn)
            items = df.to_dict('records')
            for item in items:
                if item.get('last_alarm_time') and hasattr(item['last_alarm_time'], 'isoformat'):
                    item['last_alarm_time'] = item['last_alarm_time'].isoformat()
            return items
        except Exception as e:
            print(f"[PostgreSQL] 获取设备报警列表失败: {e}")
            return []

    def create_report_tables(self):
        """创建报告相关表（扩展版）"""
        if not self.conn:
            return False

        # 扩展的设备报告表
        create_device_report = """
        CREATE TABLE IF NOT EXISTS device_report (
            id SERIAL PRIMARY KEY,

            -- 报告元信息
            report_type VARCHAR(20) NOT NULL,
            report_date DATE NOT NULL,
            period_start TIMESTAMP,
            period_end TIMESTAMP,

            -- 设备信息
            device_id VARCHAR(50),
            device_name VARCHAR(100),
            device_code VARCHAR(50),
            workshop_id VARCHAR(50),
            workshop VARCHAR(100),
            production_line_id VARCHAR(50),
            production_line VARCHAR(100),

            -- 报警统计
            alarm_count INTEGER DEFAULT 0,
            alarm_types JSONB,
            alarm_duration_seconds INTEGER DEFAULT 0,
            alarm_rate FLOAT DEFAULT 0,

            -- 健康评估
            health_score FLOAT,
            health_status VARCHAR(20),
            health_trend VARCHAR(20),
            parameter_health JSONB,

            -- 故障预测
            fault_predictions JSONB,
            risk_level VARCHAR(20),
            estimated_issues JSONB,

            -- 维护建议
            maintenance_suggestions JSONB,
            urgent_actions JSONB,
            scheduled_maintenance JSONB,

            -- AI 报告内容
            report_content TEXT,
            report_summary TEXT,

            -- 对比数据
            comparison_data JSONB,
            trend_data JSONB,

            -- 元数据
            generated_by VARCHAR(50) DEFAULT 'system',
            generation_time_seconds FLOAT,
            llm_model VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        create_report_index = """
        CREATE INDEX IF NOT EXISTS idx_device_report_date
        ON device_report(report_date);
        CREATE INDEX IF NOT EXISTS idx_device_report_type
        ON device_report(report_type);
        CREATE INDEX IF NOT EXISTS idx_device_report_device
        ON device_report(device_id);
        CREATE INDEX IF NOT EXISTS idx_device_report_type_date
        ON device_report(report_type, report_date);
        CREATE INDEX IF NOT EXISTS idx_device_report_workshop
        ON device_report(workshop_id, report_date);
        CREATE INDEX IF NOT EXISTS idx_device_report_health
        ON device_report(health_score);
        CREATE INDEX IF NOT EXISTS idx_device_report_risk
        ON device_report(risk_level);
        """

        # 车间汇总报告表
        create_workshop_summary = """
        CREATE TABLE IF NOT EXISTS workshop_report_summary (
            id SERIAL PRIMARY KEY,

            report_type VARCHAR(20) NOT NULL,
            report_date DATE NOT NULL,

            -- 汇总级别
            summary_level VARCHAR(20) NOT NULL,
            workshop_id VARCHAR(50),
            workshop_name VARCHAR(100),
            production_line_id VARCHAR(50),
            production_line_name VARCHAR(100),

            -- 汇总统计
            total_devices INTEGER DEFAULT 0,
            devices_reported INTEGER DEFAULT 0,

            -- 健康汇总
            avg_health_score FLOAT,
            min_health_score FLOAT,
            max_health_score FLOAT,
            devices_critical INTEGER DEFAULT 0,
            devices_warning INTEGER DEFAULT 0,
            devices_fair INTEGER DEFAULT 0,
            devices_good INTEGER DEFAULT 0,
            devices_excellent INTEGER DEFAULT 0,

            -- 报警汇总
            total_alarms INTEGER DEFAULT 0,
            top_alarm_devices JSONB,
            top_alarm_types JSONB,

            -- 维护汇总
            urgent_maintenance_count INTEGER DEFAULT 0,
            scheduled_maintenance_count INTEGER DEFAULT 0,

            -- AI 汇总报告
            summary_content TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        create_workshop_index = """
        CREATE INDEX IF NOT EXISTS idx_workshop_summary_date
        ON workshop_report_summary(report_type, report_date);
        CREATE INDEX IF NOT EXISTS idx_workshop_summary_level
        ON workshop_report_summary(summary_level, workshop_id);
        """

        # 报告生成任务表
        create_report_job = """
        CREATE TABLE IF NOT EXISTS report_generation_job (
            id SERIAL PRIMARY KEY,

            job_type VARCHAR(20) NOT NULL,
            job_status VARCHAR(20) NOT NULL DEFAULT 'pending',

            -- 时间范围
            report_date DATE NOT NULL,
            period_start TIMESTAMP NOT NULL,
            period_end TIMESTAMP NOT NULL,

            -- 执行信息
            total_devices INTEGER DEFAULT 0,
            processed_devices INTEGER DEFAULT 0,
            failed_devices INTEGER DEFAULT 0,

            -- 触发方式
            trigger_type VARCHAR(20) DEFAULT 'scheduled',
            triggered_by VARCHAR(100),

            -- 执行时间
            started_at TIMESTAMP,
            completed_at TIMESTAMP,

            -- 错误信息
            error_message TEXT,
            error_details JSONB,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        create_report_job_index = """
        CREATE INDEX IF NOT EXISTS idx_report_job_date
        ON report_generation_job(job_type, report_date);
        CREATE INDEX IF NOT EXISTS idx_report_job_status
        ON report_generation_job(job_status);
        """

        try:
            with self.conn.cursor() as cursor:
                cursor.execute(create_device_report)
                cursor.execute(create_report_index)
                cursor.execute(create_workshop_summary)
                cursor.execute(create_workshop_index)
                cursor.execute(create_report_job)
                cursor.execute(create_report_job_index)
                self.conn.commit()
                print("[PostgreSQL] 报告表已创建/更新")
                return True
        except Exception as e:
            self.conn.rollback()
            print(f"[PostgreSQL] 创建报告表失败: {e}")
            return False

    def save_device_report(self, report_type: str, report_date: str,
                         device_id: str = None, device_name: str = None,
                         device_code: str = None,
                         workshop_id: str = None, workshop: str = None,
                         production_line_id: str = None, production_line: str = None,
                         period_start: str = None, period_end: str = None,
                         alarm_count: int = 0, alarm_types: dict = None,
                         alarm_duration_seconds: int = 0, alarm_rate: float = 0,
                         health_score: float = None, health_status: str = None,
                         health_trend: str = None, parameter_health: dict = None,
                         fault_predictions: list = None, risk_level: str = None,
                         estimated_issues: list = None,
                         maintenance_suggestions: list = None,
                         urgent_actions: list = None,
                         scheduled_maintenance: list = None,
                         report_content: str = None, report_summary: str = None,
                         comparison_data: dict = None, trend_data: dict = None,
                         generated_by: str = 'system',
                         generation_time_seconds: float = None,
                         llm_model: str = None) -> int:
        """保存设备报告（扩展版）"""
        if not self.conn:
            return None

        sql = """
            INSERT INTO device_report (
                report_type, report_date, period_start, period_end,
                device_id, device_name, device_code,
                workshop_id, workshop, production_line_id, production_line,
                alarm_count, alarm_types, alarm_duration_seconds, alarm_rate,
                health_score, health_status, health_trend, parameter_health,
                fault_predictions, risk_level, estimated_issues,
                maintenance_suggestions, urgent_actions, scheduled_maintenance,
                report_content, report_summary,
                comparison_data, trend_data,
                generated_by, generation_time_seconds, llm_model
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, (
                    report_type, report_date, period_start, period_end,
                    device_id, device_name, device_code,
                    workshop_id, workshop, production_line_id, production_line,
                    alarm_count,
                    json.dumps(alarm_types) if alarm_types else None,
                    alarm_duration_seconds, alarm_rate,
                    health_score, health_status, health_trend,
                    json.dumps(parameter_health) if parameter_health else None,
                    json.dumps(fault_predictions) if fault_predictions else None,
                    risk_level,
                    json.dumps(estimated_issues) if estimated_issues else None,
                    json.dumps(maintenance_suggestions) if maintenance_suggestions else None,
                    json.dumps(urgent_actions) if urgent_actions else None,
                    json.dumps(scheduled_maintenance) if scheduled_maintenance else None,
                    report_content, report_summary,
                    json.dumps(comparison_data) if comparison_data else None,
                    json.dumps(trend_data) if trend_data else None,
                    generated_by, generation_time_seconds, llm_model
                ))
                self.conn.commit()
                return cursor.fetchone()[0]
        except Exception as e:
            self.conn.rollback()
            print(f"[PostgreSQL] 保存报告失败: {e}")
            return None

    def get_device_report_by_id(self, report_id: int) -> dict:
        """根据ID获取报告详情"""
        if not self.conn:
            return None

        sql = "SELECT * FROM device_report WHERE id = %s"
        df = pd.read_sql(sql, self.conn, params=(report_id,))
        if not df.empty:
            return df.iloc[0].to_dict()
        return None

    def delete_device_report(self, report_id: int) -> bool:
        """删除报告"""
        if not self.conn:
            return False

        sql = "DELETE FROM device_report WHERE id = %s"
        return self.execute(sql, (report_id,))

    # ========== 报告生成任务相关方法 ==========

    def create_report_job(self, job_type: str, report_date: str,
                         period_start: str, period_end: str,
                         trigger_type: str = 'scheduled',
                         triggered_by: str = None) -> int:
        """创建报告生成任务"""
        if not self.conn:
            return None

        sql = """
            INSERT INTO report_generation_job
            (job_type, job_status, report_date, period_start, period_end,
             trigger_type, triggered_by, started_at)
            VALUES (%s, 'running', %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id;
        """
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, (
                    job_type, report_date, period_start, period_end,
                    trigger_type, triggered_by
                ))
                self.conn.commit()
                return cursor.fetchone()[0]
        except Exception as e:
            self.conn.rollback()
            print(f"[PostgreSQL] 创建报告任务失败: {e}")
            return None

    def update_report_job_progress(self, job_id: int,
                                   total_devices: int = None,
                                   processed_devices: int = None,
                                   failed_devices: int = None) -> bool:
        """更新报告任务进度"""
        if not self.conn:
            return False

        updates = []
        params = []

        if total_devices is not None:
            updates.append("total_devices = %s")
            params.append(total_devices)
        if processed_devices is not None:
            updates.append("processed_devices = %s")
            params.append(processed_devices)
        if failed_devices is not None:
            updates.append("failed_devices = %s")
            params.append(failed_devices)

        if not updates:
            return False

        params.append(job_id)
        sql = f"UPDATE report_generation_job SET {', '.join(updates)} WHERE id = %s"
        return self.execute(sql, tuple(params))

    def complete_report_job(self, job_id: int, status: str = 'completed',
                           error_message: str = None,
                           error_details: dict = None) -> bool:
        """完成报告任务"""
        if not self.conn:
            return False

        sql = """
            UPDATE report_generation_job
            SET job_status = %s,
                completed_at = CURRENT_TIMESTAMP,
                error_message = %s,
                error_details = %s
            WHERE id = %s
        """
        return self.execute(sql, (
            status, error_message,
            json.dumps(error_details) if error_details else None,
            job_id
        ))

    def get_report_jobs(self, job_type: str = None,
                       job_status: str = None,
                       limit: int = 50) -> pd.DataFrame:
        """获取报告任务列表"""
        if not self.conn:
            return pd.DataFrame()

        conditions = []
        params = []

        if job_type:
            conditions.append("job_type = %s")
            params.append(job_type)
        if job_status:
            conditions.append("job_status = %s")
            params.append(job_status)

        sql = "SELECT * FROM report_generation_job"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        return pd.read_sql(sql, self.conn, params=tuple(params))

    def get_report_job_by_id(self, job_id: int) -> dict:
        """获取任务详情"""
        if not self.conn:
            return None

        sql = "SELECT * FROM report_generation_job WHERE id = %s"
        df = pd.read_sql(sql, self.conn, params=(job_id,))
        if not df.empty:
            return df.iloc[0].to_dict()
        return None

    # ========== 车间汇总报告相关方法 ==========

    def save_workshop_summary(self, report_type: str, report_date: str,
                             summary_level: str,
                             workshop_id: str = None, workshop_name: str = None,
                             production_line_id: str = None,
                             production_line_name: str = None,
                             total_devices: int = 0, devices_reported: int = 0,
                             avg_health_score: float = None,
                             min_health_score: float = None,
                             max_health_score: float = None,
                             devices_critical: int = 0, devices_warning: int = 0,
                             devices_fair: int = 0, devices_good: int = 0,
                             devices_excellent: int = 0,
                             total_alarms: int = 0,
                             top_alarm_devices: list = None,
                             top_alarm_types: list = None,
                             urgent_maintenance_count: int = 0,
                             scheduled_maintenance_count: int = 0,
                             summary_content: str = None) -> int:
        """保存车间汇总报告"""
        if not self.conn:
            return None

        sql = """
            INSERT INTO workshop_report_summary (
                report_type, report_date, summary_level,
                workshop_id, workshop_name,
                production_line_id, production_line_name,
                total_devices, devices_reported,
                avg_health_score, min_health_score, max_health_score,
                devices_critical, devices_warning, devices_fair,
                devices_good, devices_excellent,
                total_alarms, top_alarm_devices, top_alarm_types,
                urgent_maintenance_count, scheduled_maintenance_count,
                summary_content
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, (
                    report_type, report_date, summary_level,
                    workshop_id, workshop_name,
                    production_line_id, production_line_name,
                    total_devices, devices_reported,
                    avg_health_score, min_health_score, max_health_score,
                    devices_critical, devices_warning, devices_fair,
                    devices_good, devices_excellent,
                    total_alarms,
                    json.dumps(top_alarm_devices) if top_alarm_devices else None,
                    json.dumps(top_alarm_types) if top_alarm_types else None,
                    urgent_maintenance_count, scheduled_maintenance_count,
                    summary_content
                ))
                self.conn.commit()
                return cursor.fetchone()[0]
        except Exception as e:
            self.conn.rollback()
            print(f"[PostgreSQL] 保存车间汇总失败: {e}")
            return None

    def get_workshop_summaries(self, report_type: str = None,
                              report_date: str = None,
                              workshop_id: str = None,
                              summary_level: str = None,
                              limit: int = 100) -> pd.DataFrame:
        """获取车间汇总列表"""
        if not self.conn:
            return pd.DataFrame()

        conditions = []
        params = []

        if report_type:
            conditions.append("report_type = %s")
            params.append(report_type)
        if report_date:
            conditions.append("report_date = %s")
            params.append(report_date)
        if workshop_id:
            conditions.append("workshop_id = %s")
            params.append(workshop_id)
        if summary_level:
            conditions.append("summary_level = %s")
            params.append(summary_level)

        sql = "SELECT * FROM workshop_report_summary"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY report_date DESC, created_at DESC LIMIT %s"
        params.append(limit)

        return pd.read_sql(sql, self.conn, params=tuple(params))

    def get_device_reports(self, report_type: str = None,
                          device_id: str = None,
                          start_date: str = None,
                          end_date: str = None,
                          limit: int = 100) -> pd.DataFrame:
        """获取设备报告列表"""
        if not self.conn:
            return pd.DataFrame()

        conditions = []
        params = []

        if report_type:
            conditions.append("report_type = %s")
            params.append(report_type)
        if device_id:
            conditions.append("device_id = %s")
            params.append(device_id)
        if start_date:
            conditions.append("report_date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("report_date <= %s")
            params.append(end_date)

        sql = "SELECT * FROM device_report"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY report_date DESC, created_at DESC LIMIT %s"
        params.append(limit)

        return pd.read_sql(sql, self.conn, params=tuple(params))

    def get_report_summary(self, report_type: str, report_date: str) -> dict:
        """获取报告汇总"""
        if not self.conn:
            return {}

        sql = """
            SELECT
                COUNT(*) as total_devices,
                SUM(alarm_count) as total_alarms,
                AVG(alarm_rate) as avg_alarm_rate,
                AVG(health_score) as avg_health_score,
                COUNT(CASE WHEN health_score < 60 THEN 1 END) as low_health_count
            FROM device_report
            WHERE report_type = %s AND report_date = %s
        """
        df = pd.read_sql(sql, self.conn, params=(report_type, report_date))
        if not df.empty:
            return df.iloc[0].to_dict()
        return {}


    # ==================== 报警分析报告 ====================

    def create_alarm_analysis_tables(self):
        """创建报警分析报告表（日报/周报/月报）"""
        if not self.conn:
            return False

        create_daily = """
        CREATE TABLE IF NOT EXISTS alarm_analysis_daily (
            id SERIAL PRIMARY KEY,
            report_date DATE NOT NULL,
            device_id VARCHAR(50),
            statistics JSONB,
            analysis JSONB,
            query_params JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(report_date, device_id)
        );
        """

        create_weekly = """
        CREATE TABLE IF NOT EXISTS alarm_analysis_weekly (
            id SERIAL PRIMARY KEY,
            report_date DATE NOT NULL,
            device_id VARCHAR(50),
            statistics JSONB,
            analysis JSONB,
            query_params JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(report_date, device_id)
        );
        """

        create_monthly = """
        CREATE TABLE IF NOT EXISTS alarm_analysis_monthly (
            id SERIAL PRIMARY KEY,
            report_date DATE NOT NULL,
            device_id VARCHAR(50),
            statistics JSONB,
            analysis JSONB,
            query_params JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(report_date, device_id)
        );
        """

        create_index = """
        CREATE INDEX IF NOT EXISTS idx_alarm_daily_date ON alarm_analysis_daily(report_date);
        CREATE INDEX IF NOT EXISTS idx_alarm_weekly_date ON alarm_analysis_weekly(report_date);
        CREATE INDEX IF NOT EXISTS idx_alarm_monthly_date ON alarm_analysis_monthly(report_date);
        """

        try:
            with self.conn.cursor() as cursor:
                cursor.execute(create_daily)
                cursor.execute(create_weekly)
                cursor.execute(create_monthly)
                cursor.execute(create_index)
                self.conn.commit()
                print("[PostgreSQL] 报警分析表已创建")
                return True
        except Exception as e:
            self.conn.rollback()
            print(f"[PostgreSQL] 创建报警分析表失败: {e}")
            return False

    def save_alarm_analysis(self, report_type: str, report_date: str,
                            device_id: str, statistics: dict,
                            analysis: dict, query_params: dict) -> int:
        """保存报警分析结果（UNIQUE 约束自动覆盖）"""
        if not self.conn:
            return None

        table_map = {
            'daily': 'alarm_analysis_daily',
            'weekly': 'alarm_analysis_weekly',
            'monthly': 'alarm_analysis_monthly',
        }
        table = table_map.get(report_type)
        if not table:
            return None

        sql = """
            INSERT INTO {} (report_date, device_id, statistics, analysis, query_params, updated_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (report_date, device_id)
            DO UPDATE SET
                statistics = EXCLUDED.statistics,
                analysis = EXCLUDED.analysis,
                query_params = EXCLUDED.query_params,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id;
        """.format(table)
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, (
                    report_date,
                    device_id or 'all',
                    json.dumps(statistics, default=str),
                    json.dumps(analysis, default=str),
                    json.dumps(query_params, default=str),
                ))
                self.conn.commit()
                return cursor.fetchone()[0]
        except Exception as e:
            self.conn.rollback()
            print(f"[PostgreSQL] 保存报警分析失败: {e}")
            return None

    def get_alarm_analysis(self, report_type: str, report_date: str,
                           device_id: str = None) -> dict:
        """获取报警分析结果"""
        if not self.conn:
            return None

        table_map = {
            'daily': 'alarm_analysis_daily',
            'weekly': 'alarm_analysis_weekly',
            'monthly': 'alarm_analysis_monthly',
        }
        table = table_map.get(report_type)
        if not table:
            return None

        sql = """
            SELECT id, report_date, device_id, statistics, analysis, query_params,
                   created_at, updated_at
            FROM {}
            WHERE report_date = %s
        """.format(table)
        params = [report_date]
        if device_id:
            sql += " AND device_id = %s"
            params.append(device_id)
        sql += " ORDER BY updated_at DESC LIMIT 1"

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, tuple(params))
                row = cursor.fetchone()
                if row:
                    result = dict(row)
                    # 处理时间字段
                    for key in ['created_at', 'updated_at', 'report_date']:
                        if result.get(key) and hasattr(result[key], 'isoformat'):
                            result[key] = result[key].isoformat()
                    return result
                return None
        except Exception as e:
            print(f"[PostgreSQL] 获取报警分析失败: {e}")
            return None

    def list_alarm_analyses(self, report_type: str, limit: int = 50) -> list:
        """列出报警分析报告历史"""
        if not self.conn:
            return []

        table_map = {
            'daily': 'alarm_analysis_daily',
            'weekly': 'alarm_analysis_weekly',
            'monthly': 'alarm_analysis_monthly',
        }
        table = table_map.get(report_type)
        if not table:
            return []

        sql = """
            SELECT id, report_date, device_id,
                   statistics->>'total' as total_alarms,
                   statistics->>'active' as active_alarms,
                   analysis->>'total_anomalies' as total_anomalies,
                   analysis->'severity_distribution' as severity,
                   created_at, updated_at
            FROM {}
            ORDER BY report_date DESC, updated_at DESC
            LIMIT %s
        """.format(table)
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, (limit,))
                rows = cursor.fetchall()
                result = []
                for row in rows:
                    item = dict(row)
                    for key in ['created_at', 'updated_at', 'report_date']:
                        if item.get(key) and hasattr(item[key], 'isoformat'):
                            item[key] = item[key].isoformat()
                    result.append(item)
                return result
        except Exception as e:
            print(f"[PostgreSQL] 列出报警分析失败: {e}")
            return []


# 兼容旧代码
class PostgresConnector(PostgresDB):
    """兼容旧代码的连接器"""

    def __init__(self, host: str = None, port: int = None,
                 user: str = None, password: str = None,
                 use_fallback: bool = False):
        super().__init__()


if __name__ == "__main__":
    db = PostgresDB()
    if db.connect_with_fallback():
        print("连接成功")

        # 创建Job表
        db.create_job_tables()

        # 测试Job记录
        job_id = db.start_job("test_job")
        print(f"Job ID: {job_id}")

        db.add_job_log(job_id, "info", "测试日志")
        db.add_job_log(job_id, "warning", "测试警告", {"detail": "test"})

        db.end_job(job_id, "success", {"result": "ok"})

        # 查询状态
        df = db.get_job_status("test_job")
        print("\nJob状态:")
        print(df.to_string())

        db.close()