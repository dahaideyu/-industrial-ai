# cython: annotation_typing=False, infer_types=False, language_level=3
"""
数据加载模块 - 从PostgreSQL加载报警信息和历史数据
所有数据来自TimescaleDB (PostgreSQL) 数据库
"""
import os
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from pathlib import Path

from .point_config import get_logic_name, get_display_name, get_alarm_name


class DataLoader:
    """数据加载器 - PostgreSQL数据源"""

    def __init__(self, data_dir: str = "."):
        self.data_dir = Path(data_dir)
        self.alarm_definitions: Dict[str, pd.DataFrame] = {}
        self.history_data: Dict[str, pd.DataFrame] = {}

    def load_alarm_definitions(self) -> Dict[str, pd.DataFrame]:
        """从PostgreSQL加载报警定义"""
        from .postgres_loader import PostgresConnector

        db = PostgresConnector()
        if not db.connect_with_fallback():
            raise ConnectionError("无法连接到PostgreSQL数据库")

        try:
            point_df = db.get_table_data("point_info")
            device_df = db.get_table_data("device_info")

            for _, device in device_df.iterrows():
                device_id = device['device_id']
                device_name = device['device_name']

                device_points = point_df[point_df['belong_devide'] == device_id]
                if not device_points.empty:
                    alarm_df = device_points[['point_id', 'point_name', 'remark']].copy()
                    alarm_df.columns = ['点位标识', '点位名称', '备注']
                    self.alarm_definitions[device_name] = alarm_df

            db.close()
            return self.alarm_definitions
        except Exception as e:
            db.close()
            raise RuntimeError(f"加载报警定义失败: {e}")

    def load_history_data(self, device_id: str = None,
                   start_time: str = None,
                   hours: int = 24,
                   use_logic_names: bool = True) -> Dict[str, pd.DataFrame]:
        """从PostgreSQL加载历史/实时数据

        Args:
            device_id: 设备ID (默认正1#金帆球磨机: 102000018415)
            start_time: 开始时间 ISO格式 (默认24小时前)
            hours: 小时数
            use_logic_names: 是否将工艺参数point_id映射为中文逻辑名

        Returns:
            Dict[str, pd.DataFrame] - 按参数名分组的时序数据
        """
        from .postgres_loader import PostgresConnector
        import datetime

        db = PostgresConnector()
        if not db.connect_with_fallback():
            raise ConnectionError("无法连接到PostgreSQL数据库")

        try:
            if device_id is None:
                device_id = "102000018415"

            if start_time is None:
                start_time = (datetime.datetime.now() -
                              datetime.timedelta(hours=hours)).isoformat()

            query = """
                SELECT point_id, point_value, point_time, device_status
                FROM device_alarm_info
                WHERE device_id = %s AND point_time >= %s
                ORDER BY point_time
            """

            df = db.query(query, (device_id, start_time))

            result = {}
            if not df.empty:
                for point_id, group in df.groupby('point_id'):
                    param_df = group[['point_time', 'point_value']].copy()
                    param_df.columns = ['采集时间', '参数值']
                    param_df['采集时间'] = pd.to_datetime(param_df['采集时间'])
                    param_df = param_df.sort_values('采集时间').reset_index(drop=True)

                    # 映射为中文逻辑名（用于预测模块）
                    key = point_id
                    if use_logic_names:
                        logic_name = get_logic_name(device_id, point_id)
                        if logic_name != point_id:
                            key = logic_name
                        else:
                            # 尝试映射报警参数名
                            alarm_name = get_alarm_name(device_id, point_id)
                            if alarm_name != point_id:
                                key = alarm_name

                    result[key] = param_df

            self.history_data = result
            db.close()
            return self.history_data
        except Exception as e:
            db.close()
            raise RuntimeError(f"加载历史数据失败: {e}")

    def load_alarm_events(self, device_id: str = None,
                     start_time: str = None,
                     hours: int = 24,
                     only_alerts: bool = True,
                     use_logic_names: bool = True) -> pd.DataFrame:
        """从PostgreSQL加载报警事件

        Args:
            device_id: 设备ID
            start_time: 开始时间
            hours: 小时数
            only_alerts: 只返回value=1的报警事件
            use_logic_names: 是否将point_id映射为中文报警名

        Returns:
            pd.DataFrame - 报警事件数据
        """
        from .postgres_loader import PostgresConnector
        import datetime

        db = PostgresConnector()
        if not db.connect_with_fallback():
            raise ConnectionError("无法连接到PostgreSQL数据库")

        try:
            if device_id is None:
                device_id = "102000018415"

            if start_time is None:
                start_time = (datetime.datetime.now() -
                              datetime.timedelta(hours=hours)).isoformat()

            query = """
                SELECT d.device_id, d.device_name, a.point_id, a.point_value,
                       a.point_time, a.device_status
                FROM device_alarm_info a
                LEFT JOIN device_info d ON a.device_id = d.device_id
                WHERE a.device_id = %s AND a.point_time >= %s
            """

            params = [device_id, start_time]
            if only_alerts:
                query += " AND a.point_value = 1"
            query += " ORDER BY a.point_time DESC"

            df = db.query(query, tuple(params))

            # 补充中文报警名
            if use_logic_names and not df.empty:
                df['报警名称'] = df['point_id'].apply(
                    lambda pid: get_alarm_name(device_id, pid)
                )

            db.close()
            return df
        except Exception as e:
            db.close()
            raise RuntimeError(f"加载报警事件失败: {e}")

    def get_device_list(self) -> List[Dict]:
        """获取设备列表"""
        from .postgres_loader import PostgresConnector

        db = PostgresConnector()
        if not db.connect_with_fallback():
            return []

        df = db.get_table_data("device_info")
        db.close()

        return df.to_dict('records')

    def get_point_list(self, device_id: str = None) -> pd.DataFrame:
        """获取点位列表"""
        from .postgres_loader import PostgresConnector

        db = PostgresConnector()
        if not db.connect_with_fallback():
            return pd.DataFrame()

        try:
            if device_id:
                df = db.query(
                    "SELECT * FROM point_info WHERE belong_devide = %s",
                    (device_id,)
                )
            else:
                df = db.get_table_data("point_info")

            db.close()
            return df
        except Exception as e:
            db.close()
            return pd.DataFrame()

    def get_merged_timeseries(self) -> pd.DataFrame:
        """获取合并后的时序数据（所有参数对齐到同一时间轴）"""
        if not self.history_data:
            self.load_history_data()

        merged = None
        for param_name, df in self.history_data.items():
            param_df = df[['采集时间', '参数值']].copy()
            param_df = param_df.rename(columns={'参数值': param_name})
            param_df = param_df.set_index('采集时间')

            if merged is None:
                merged = param_df
            else:
                merged = merged.join(param_df, how='outer')

        merged = merged.sort_index()
        return merged

    def get_statistics(self) -> pd.DataFrame:
        """获取各参数的统计信息"""
        if not self.history_data:
            self.load_history_data()

        stats = []
        for param_name, df in self.history_data.items():
            values = df['参数值'].dropna()
            if len(values) > 0:
                stats.append({
                    '参数': param_name,
                    '数据点数': len(values),
                    '最小值': values.min(),
                    '最大值': values.max(),
                    '平均值': values.mean(),
                    '标准差': values.std(),
                    '中位数': values.median(),
                    '25%分位': values.quantile(0.25),
                    '75%分位': values.quantile(0.75)
                })

        return pd.DataFrame(stats)


if __name__ == "__main__":
    loader = DataLoader()

    print("加载报警定义...")
    alarms = loader.load_alarm_definitions()
    for name, df in alarms.items():
        print(f"  {name}: {len(df)} 种报警")

    print("\n加载历史数据...")
    history = loader.load_history_data(hours=1)
    print(f"  加载 {len(history)} 个参数")

    print("\n统计信息:")
    stats = loader.get_statistics()
    print(stats.to_string())