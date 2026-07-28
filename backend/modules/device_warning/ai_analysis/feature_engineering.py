# cython: annotation_typing=False, infer_types=False, language_level=3
"""
特征工程模块 - 设备数据宽表与特征生成

将原始时序参数 + 告警事件加工为可供模型使用的特征宽表。

P0 任务 1: 统一宽表生成
- 输入: device_id + 时间窗口
- 输出: 以参数时间轴为主，每行包含所有参数值 + 告警标志列 + alarm_list JSON

后续任务（任务 2-6）将扩展此类，加入运行状态标记、滑动窗口特征、
交互特征、告警滚动窗口特征。
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .data_loader import DataLoader
from .point_config import ALARM_POINT_NAMES, get_alarm_name


class FeatureEngineer:
    """特征工程统一入口

    依赖 DataLoader 提供 load_history_data / load_alarm_events 两个数据源。
    """

    DEFAULT_ALARM_TOLERANCE_SECONDS = 2
    ALARM_COL_SUFFIX = "_active"
    ALARM_LIST_COL = "alarm_list"

    def __init__(self, data_loader: Optional[DataLoader] = None,
                 alarm_tolerance_seconds: int = DEFAULT_ALARM_TOLERANCE_SECONDS):
        self.data_loader = data_loader or DataLoader()
        self.alarm_tolerance_seconds = alarm_tolerance_seconds

    # ==================== P0 任务 1: 统一宽表生成 ====================
    def _build_wide_table(self, device_id: str, hours: int = 24,
                          start_time: Optional[str] = None) -> pd.DataFrame:
        """生成参数 + 告警宽表

        Args:
            device_id: 设备ID
            hours: 时间窗口（小时）
            start_time: 起始时间 ISO 字符串；默认 now - hours

        Returns:
            DataFrame:
                - index: pd.DatetimeIndex (名为 '时间戳')，按时间升序，去重
                - 数值列: 各工艺参数（中文逻辑名），例如 主轴温度、主机功率 ...
                - 告警标志列: f"{告警名}_active"，0/1
                - alarm_list 列: JSON list[str]，记录该时间点容忍窗口内触发的所有告警名
        """
        params = self.data_loader.load_history_data(
            device_id=device_id,
            start_time=start_time,
            hours=hours,
            use_logic_names=True,
        )
        param_wide = self._merge_param_timeline(params)

        alarms = self.data_loader.load_alarm_events(
            device_id=device_id,
            start_time=start_time,
            hours=hours,
            only_alerts=True,
            use_logic_names=True,
        )

        return self._join_alarms_to_timeline(param_wide, alarms, device_id)

    @staticmethod
    def _merge_param_timeline(params: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """将所有参数按时间外连接到统一时间轴

        Args:
            params: DataLoader.load_history_data 的返回值，
                    每个 DataFrame 含 '采集时间' 与 '参数值' 两列
        """
        if not params:
            return pd.DataFrame()

        merged: Optional[pd.DataFrame] = None
        for name, df in params.items():
            if df is None or df.empty:
                continue
            piece = df[['采集时间', '参数值']].copy()
            piece['采集时间'] = pd.to_datetime(piece['采集时间'])
            piece = piece.rename(columns={'参数值': name})
            piece = (piece
                     .drop_duplicates(subset='采集时间', keep='last')
                     .set_index('采集时间')
                     .sort_index())
            merged = piece if merged is None else merged.join(piece, how='outer')

        if merged is None:
            return pd.DataFrame()

        merged.index.name = '时间戳'
        return merged.sort_index()

    def _join_alarms_to_timeline(self, param_wide: pd.DataFrame,
                                 alarms: pd.DataFrame,
                                 device_id: str) -> pd.DataFrame:
        """将告警事件按时间容忍窗口对齐到参数时间轴

        每种已知告警都会生成一列 f"{告警名}_active"，列顺序按 point_config
        中的告警字典顺序固定，保证宽表结构稳定（即便此次窗口没触发任何此类告警）。
        """
        result = param_wide.copy() if param_wide is not None else pd.DataFrame()

        known_alarm_names = list(ALARM_POINT_NAMES.get(device_id, {}).values())
        alarm_cols = [f"{name}{self.ALARM_COL_SUFFIX}" for name in known_alarm_names]
        for col in alarm_cols:
            result[col] = 0

        if result.empty:
            result[self.ALARM_LIST_COL] = pd.Series(dtype=object)
            return result

        if alarms is None or alarms.empty:
            result[self.ALARM_LIST_COL] = json.dumps([], ensure_ascii=False)
            return result

        alarms = alarms.copy()
        alarms['point_time'] = pd.to_datetime(alarms['point_time'])
        if '报警名称' not in alarms.columns:
            alarms['报警名称'] = alarms['point_id'].apply(
                lambda pid: get_alarm_name(device_id, pid)
            )

        sorted_alarms = (alarms[['point_time', '报警名称']]
                         .dropna()
                         .sort_values('point_time')
                         .reset_index(drop=True))

        # 用 searchsorted 在参数时间轴上批量定位每个告警事件的影响范围
        param_times = result.index.values.astype('datetime64[ns]')
        tol_td = np.timedelta64(self.alarm_tolerance_seconds, 's')

        col_index = {col: result.columns.get_loc(col) for col in alarm_cols}
        active_matrix = result[alarm_cols].to_numpy(dtype=np.int8, copy=True)

        for alarm_time, alarm_name in zip(sorted_alarms['point_time'].values,
                                          sorted_alarms['报警名称'].values):
            col = f"{alarm_name}{self.ALARM_COL_SUFFIX}"
            if col not in col_index:
                continue
            at = np.datetime64(alarm_time, 'ns')
            lo = np.searchsorted(param_times, at - tol_td, side='left')
            hi = np.searchsorted(param_times, at + tol_td, side='right')
            if hi > lo:
                local_idx = alarm_cols.index(col)
                active_matrix[lo:hi, local_idx] = 1

        # 写回数值列
        for col in alarm_cols:
            result[col] = active_matrix[:, alarm_cols.index(col)]

        # alarm_list: 每行触发的告警名 JSON list
        alarm_names_arr = np.array(known_alarm_names, dtype=object)
        result[self.ALARM_LIST_COL] = [
            json.dumps(list(alarm_names_arr[row.astype(bool)]), ensure_ascii=False)
            for row in active_matrix
        ]

        return result


if __name__ == "__main__":
    fe = FeatureEngineer()
    df = fe._build_wide_table("102000018415", hours=24)
    print(f"宽表 shape: {df.shape}")
    print(f"前 20 列: {df.columns.tolist()[:20]}")
    print(f"含 '_active' 后缀的告警列数: {sum(1 for c in df.columns if c.endswith('_active'))}")
    if not df.empty:
        triggered = df[df['alarm_list'] != '[]']
        print(f"有告警的时间点数: {len(triggered)}")
        print("前 3 行预览:")
        print(df.head(3))
