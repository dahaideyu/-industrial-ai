# cython: annotation_typing=False, infer_types=False, language_level=3
"""
数据聚合服务 - 从 PostgreSQL 聚合设备报警数据
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import pandas as pd

import sys
_module_path = Path(__file__).parent.parent.parent / "device_warning" / "ai_analysis"
if str(_module_path) not in sys.path:
    sys.path.insert(0, str(_module_path))

from modules.device_warning.ai_analysis.postgres_loader import PostgresDB
from modules.device_warning.ai_analysis.data_loader import DataLoader
from modules.device_warning.ai_analysis.point_config import get_alarm_name, get_logic_name


class DataAggregator:
    """数据聚合器 - 聚合设备报警和运行数据"""

    def __init__(self):
        self.db = PostgresDB()
        self.data_loader = DataLoader()
        self._devices_cache = None

    def _load_devices(self) -> List[Dict]:
        """加载设备列表"""
        if self._devices_cache:
            return self._devices_cache

        devices_path = Path(__file__).parent.parent.parent.parent / "data" / "devices.json"
        if not devices_path.exists():
            print(f"[警告] 设备配置文件不存在: {devices_path}")
            return []

        try:
            with open(devices_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            devices = []
            for workshop in data.get("workshops", []):
                for line in workshop.get("production_lines", []):
                    for device in line.get("devices", []):
                        devices.append({
                            "id": device["id"],
                            "name": device["name"],
                            "device_code": device.get("device_code", device["id"]),
                            "workshop_id": workshop["id"],
                            "workshop_name": workshop["name"],
                            "production_line_id": line["id"],
                            "production_line_name": line["name"]
                        })
            self._devices_cache = devices
            return devices
        except Exception as e:
            print(f"[错误] 加载设备列表失败: {e}")
            return []

    def get_device_info(self, device_id: str) -> Optional[Dict]:
        """获取设备信息"""
        devices = self._load_devices()
        for device in devices:
            if device["id"] == device_id:
                return device
        return None

    def get_all_devices(self) -> List[Dict]:
        """获取所有设备"""
        return self._load_devices()

    def get_devices_by_workshop(self, workshop_id: str) -> List[Dict]:
        """获取指定车间的设备"""
        devices = self._load_devices()
        return [d for d in devices if d["workshop_id"] == workshop_id]

    def aggregate_device_data(
        self,
        device_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> Dict:
        """
        聚合单台设备在指定时间段的数据

        Args:
            device_id: 设备ID
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            {
                "device_id": str,
                "device_name": str,
                "device_info": Dict,
                "period": {"start": datetime, "end": datetime},
                "alarm_stats": {...},
                "history_data": Dict[str, pd.DataFrame],
                "alarm_events": pd.DataFrame
            }
        """
        device_info = self.get_device_info(device_id)

        # 加载历史数据
        hours = int((end_time - start_time).total_seconds() / 3600)
        history_data = self.data_loader.load_history_data(
            device_id=device_id,
            start_time=start_time.isoformat(),
            hours=hours
        )

        # 加载报警事件
        alarm_events = self.data_loader.load_alarm_events(
            device_id=device_id,
            start_time=start_time.isoformat(),
            hours=hours,
            only_alerts=True
        )

        # 计算报警统计
        alarm_stats = self._calculate_alarm_stats(alarm_events, start_time, end_time)

        return {
            "device_id": device_id,
            "device_name": device_info["name"] if device_info else device_id,
            "device_info": device_info,
            "period": {"start": start_time, "end": end_time},
            "alarm_stats": alarm_stats,
            "history_data": history_data,
            "alarm_events": alarm_events
        }

    def _calculate_alarm_stats(
        self,
        alarm_events: pd.DataFrame,
        start_time: datetime,
        end_time: datetime
    ) -> Dict:
        """计算报警统计"""
        total_seconds = (end_time - start_time).total_seconds()

        if alarm_events.empty:
            return {
                "total_count": 0,
                "alarm_types": {},
                "alarm_duration_seconds": 0,
                "alarm_rate": 0.0,
                "top_alarms": []
            }

        # 统计各类报警次数
        alarm_types = {}
        if "报警名称" in alarm_events.columns:
            alarm_types = alarm_events["报警名称"].value_counts().to_dict()
        elif "point_id" in alarm_events.columns:
            alarm_types = alarm_events["point_id"].value_counts().to_dict()

        # 估算报警时长（假设每次报警持续5分钟）
        alarm_duration = len(alarm_events) * 300  # 5分钟 = 300秒

        # 计算报警率
        alarm_rate = (alarm_duration / total_seconds) * 100 if total_seconds > 0 else 0

        # Top 报警
        top_alarms = [
            {"name": name, "count": count}
            for name, count in sorted(alarm_types.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

        return {
            "total_count": len(alarm_events),
            "alarm_types": alarm_types,
            "alarm_duration_seconds": alarm_duration,
            "alarm_rate": min(alarm_rate, 100.0),
            "top_alarms": top_alarms
        }

    def aggregate_all_devices(
        self,
        start_time: datetime,
        end_time: datetime,
        device_ids: List[str] = None
    ) -> List[Dict]:
        """
        聚合所有设备的数据

        Args:
            start_time: 开始时间
            end_time: 结束时间
            device_ids: 可选，指定设备ID列表

        Returns:
            设备数据列表
        """
        if device_ids:
            devices = [{"id": did} for did in device_ids]
        else:
            devices = self._load_devices()

        results = []
        for device in devices:
            try:
                data = self.aggregate_device_data(
                    device["id"], start_time, end_time
                )
                results.append(data)
            except Exception as e:
                print(f"[错误] 聚合设备 {device['id']} 数据失败: {e}")
                continue

        return results

    def get_comparison_data(
        self,
        device_id: str,
        current_period: Tuple[datetime, datetime],
        previous_period: Tuple[datetime, datetime]
    ) -> Dict:
        """
        获取对比数据 (用于周报/月报的环比分析)

        Args:
            device_id: 设备ID
            current_period: 当前周期 (start, end)
            previous_period: 上一周期 (start, end)

        Returns:
            对比数据
        """
        # 当前周期数据
        current_data = self.aggregate_device_data(
            device_id, current_period[0], current_period[1]
        )

        # 上一周期数据
        previous_data = self.aggregate_device_data(
            device_id, previous_period[0], previous_period[1]
        )

        current_stats = current_data["alarm_stats"]
        previous_stats = previous_data["alarm_stats"]

        # 计算变化
        alarm_change = current_stats["total_count"] - previous_stats["total_count"]
        alarm_change_pct = (
            (alarm_change / previous_stats["total_count"] * 100)
            if previous_stats["total_count"] > 0 else 0
        )

        return {
            "current_period": {
                "start": current_period[0].isoformat(),
                "end": current_period[1].isoformat(),
                "alarm_count": current_stats["total_count"],
                "alarm_rate": current_stats["alarm_rate"]
            },
            "previous_period": {
                "start": previous_period[0].isoformat(),
                "end": previous_period[1].isoformat(),
                "alarm_count": previous_stats["total_count"],
                "alarm_rate": previous_stats["alarm_rate"]
            },
            "comparison": {
                "alarm_count_change": alarm_change,
                "alarm_count_change_pct": round(alarm_change_pct, 1),
                "alarm_rate_change": round(
                    current_stats["alarm_rate"] - previous_stats["alarm_rate"], 2
                ),
                "trend": "up" if alarm_change > 0 else ("down" if alarm_change < 0 else "stable")
            }
        }

    def get_trend_data(
        self,
        device_id: str,
        start_time: datetime,
        end_time: datetime,
        interval: str = "daily"
    ) -> List[Dict]:
        """
        获取趋势数据

        Args:
            device_id: 设备ID
            start_time: 开始时间
            end_time: 结束时间
            interval: 间隔 (daily/hourly)

        Returns:
            趋势数据列表
        """
        if interval == "daily":
            delta = timedelta(days=1)
        else:
            delta = timedelta(hours=1)

        trend = []
        current = start_time

        while current < end_time:
            period_end = min(current + delta, end_time)

            try:
                data = self.aggregate_device_data(device_id, current, period_end)
                trend.append({
                    "timestamp": current.isoformat(),
                    "alarm_count": data["alarm_stats"]["total_count"],
                    "alarm_rate": data["alarm_stats"]["alarm_rate"]
                })
            except Exception:
                trend.append({
                    "timestamp": current.isoformat(),
                    "alarm_count": 0,
                    "alarm_rate": 0
                })

            current = period_end

        return trend

    def get_period(self, report_type: str, report_date: datetime) -> Tuple[datetime, datetime]:
        """
        根据报告类型计算数据周期

        Args:
            report_type: 报告类型 (daily/weekly/monthly)
            report_date: 报告日期

        Returns:
            (开始时间, 结束时间)
        """
        # 结束时间为报告日期的凌晨0点
        end_time = report_date.replace(hour=0, minute=0, second=0, microsecond=0)

        if report_type == "daily":
            start_time = end_time - timedelta(days=1)
        elif report_type == "weekly":
            start_time = end_time - timedelta(days=7)
        elif report_type == "monthly":
            start_time = end_time - timedelta(days=30)
        else:
            start_time = end_time - timedelta(days=1)

        return start_time, end_time

    def get_previous_period(
        self,
        report_type: str,
        current_start: datetime
    ) -> Tuple[datetime, datetime]:
        """
        获取上一周期

        Args:
            report_type: 报告类型
            current_start: 当前周期开始时间

        Returns:
            (上周期开始时间, 上周期结束时间)
        """
        end_time = current_start

        if report_type == "weekly":
            start_time = end_time - timedelta(days=7)
        elif report_type == "monthly":
            start_time = end_time - timedelta(days=30)
        else:
            start_time = end_time - timedelta(days=1)

        return start_time, end_time
