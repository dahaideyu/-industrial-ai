# cython: annotation_typing=False, infer_types=False, language_level=3
"""
异常检测模块 - 基于统计方法和机器学习的异常检测
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class AnomalyType(Enum):
    """异常类型"""
    SPIKE = "突变"           # 突然升高或降低
    DRIFT = "漂移"           # 缓慢偏离正常范围
    THRESHOLD = "越限"       # 超过阈值
    PATTERN = "模式异常"     # 异常模式（如周期性丢失）
    FROZEN = "卡死"          # 数据不变化


@dataclass
class Anomaly:
    """异常记录"""
    timestamp: datetime
    parameter: str
    value: float
    anomaly_type: AnomalyType
    severity: str  # 低/中/高/严重
    description: str
    baseline_value: float
    deviation: float


@dataclass
class AlarmPrediction:
    """报警预测"""
    timestamp: datetime
    predicted_alarm: str
    probability: float
    estimated_time_to_alarm: timedelta
    contributing_factors: List[str]
    recommendation: str


class AnomalyDetector:
    """异常检测器"""

    # 参数配置：(正常下限, 正常上限, 报警下限, 报警上限)
    PARAMETER_THRESHOLDS = {
        '铅粒仓重量': (15000, 38000, 10000, 40000),
        '中段温度': (180, 220, 150, 230),
        '后段温度': (180, 220, 150, 230),
        '前段温度': (180, 220, 150, 230),
        '主机功率': (90, 106, 80, 110),
        '负压风压': (180, 230, 150, 250),
        '正压风压': (450, 535, 400, 550),
        '铅粉温度': (90, 115, 80, 120),
        '布袋压差': (40, 70, 30, 80),
        '过滤器压差': (70, 95, 60, 100)
    }

    # 报警与参数的关联
    ALARM_PARAMETER_MAPPING = {
        '负风风压下限报警': ('负压风压', 'lower'),
        '负风风压上限报警': ('负压风压', 'upper'),
        '正风风压下限报警': ('正压风压', 'lower'),
        '正风风压上限报警': ('正压风压', 'upper'),
        '后温下限报警': ('后段温度', 'lower'),
        '后温上限报警': ('后段温度', 'upper'),
        '中温下限报警': ('中段温度', 'lower'),
        '中温上限报警': ('中段温度', 'upper'),
        '前温下限报警': ('前段温度', 'lower'),
        '前温上限报警': ('前段温度', 'upper'),
        '电机功率下限报警': ('主机功率', 'lower'),
        '电机功率上限报警': ('主机功率', 'upper'),
        '布袋压差报警': ('布袋压差', 'upper'),
        '过滤器压差报警': ('过滤器压差', 'upper'),
    }

    def __init__(self, config: dict = None):
        self.baselines = {}  # 各参数的基线统计
        self.anomalies = []  # 检测到的异常
        self.predictions = []  # 报警预测
        self.config = config or {}
        # 使用传入配置覆盖默认值
        self.parameter_thresholds = self.config.get('parameter_thresholds', self.PARAMETER_THRESHOLDS)
        self.alarm_parameter_mapping = self.config.get('alarm_parameter_mapping', self.ALARM_PARAMETER_MAPPING)

    def calculate_baselines(self, history_data: Dict[str, pd.DataFrame]) -> Dict:
        """计算各参数的基线统计值"""
        for param_name, df in history_data.items():
            values = df['参数值'].dropna()

            # 使用稳健统计（去除异常值后）
            q1 = values.quantile(0.05)
            q3 = values.quantile(0.95)
            iqr = q3 - q1
            filtered = values[(values >= q1 - 1.5*iqr) & (values <= q3 + 1.5*iqr)]

            self.baselines[param_name] = {
                'mean': filtered.mean(),
                'std': filtered.std(),
                'median': filtered.median(),
                'q05': q1,
                'q95': q3,
                'min': filtered.min(),
                'max': filtered.max(),
                'raw_values': values.values  # 用于计算移动统计
            }

        return self.baselines

    def detect_anomalies(self, history_data: Dict[str, pd.DataFrame]) -> List[Anomaly]:
        """检测所有参数的异常"""
        self.anomalies = []

        if not self.baselines:
            self.calculate_baselines(history_data)

        for param_name, df in history_data.items():
            param_anomalies = self._detect_parameter_anomalies(param_name, df)
            self.anomalies.extend(param_anomalies)

        # 按时间排序
        self.anomalies.sort(key=lambda x: x.timestamp)

        return self.anomalies

    def _detect_parameter_anomalies(self, param_name: str, df: pd.DataFrame) -> List[Anomaly]:
        """检测单个参数的异常"""
        anomalies = []
        baseline = self.baselines.get(param_name, {})
        thresholds = self.PARAMETER_THRESHOLDS.get(param_name)

        if not baseline or thresholds is None:
            return anomalies

        normal_low, normal_high, alarm_low, alarm_high = thresholds
        mean_val = baseline['mean']
        std_val = baseline['std']

        # 遍历数据点检测异常
        values = df['参数值'].values
        timestamps = df['采集时间'].values

        for i in range(len(values)):
            val = values[i]
            ts = pd.to_datetime(timestamps[i])

            if pd.isna(val):
                continue

            anomaly = None

            # 1. 检测越限异常
            if val < alarm_low:
                severity = "严重" if val < alarm_low * 0.9 else "高"
                anomaly = Anomaly(
                    timestamp=ts,
                    parameter=param_name,
                    value=val,
                    anomaly_type=AnomalyType.THRESHOLD,
                    severity=severity,
                    description=f"{param_name}低于报警下限 ({val:.1f} < {alarm_low})",
                    baseline_value=mean_val,
                    deviation=(alarm_low - val) / std_val if std_val > 0 else 0
                )
            elif val > alarm_high:
                severity = "严重" if val > alarm_high * 1.1 else "高"
                anomaly = Anomaly(
                    timestamp=ts,
                    parameter=param_name,
                    value=val,
                    anomaly_type=AnomalyType.THRESHOLD,
                    severity=severity,
                    description=f"{param_name}超过报警上限 ({val:.1f} > {alarm_high})",
                    baseline_value=mean_val,
                    deviation=(val - alarm_high) / std_val if std_val > 0 else 0
                )
            elif val < normal_low:
                anomaly = Anomaly(
                    timestamp=ts,
                    parameter=param_name,
                    value=val,
                    anomaly_type=AnomalyType.DRIFT,
                    severity="中",
                    description=f"{param_name}低于正常范围 ({val:.1f} < {normal_low})",
                    baseline_value=mean_val,
                    deviation=(normal_low - val) / std_val if std_val > 0 else 0
                )
            elif val > normal_high:
                anomaly = Anomaly(
                    timestamp=ts,
                    parameter=param_name,
                    value=val,
                    anomaly_type=AnomalyType.DRIFT,
                    severity="中",
                    description=f"{param_name}超过正常范围 ({val:.1f} > {normal_high})",
                    baseline_value=mean_val,
                    deviation=(val - normal_high) / std_val if std_val > 0 else 0
                )

            # 2. 检测突变（与前一时刻相比）
            if i > 0 and not pd.isna(values[i-1]):
                change_rate = abs(val - values[i-1]) / (abs(values[i-1]) + 1e-6)
                if change_rate > 0.15:  # 变化超过15%
                    if anomaly is None or anomaly.severity in ["低", "中"]:
                        anomaly = Anomaly(
                            timestamp=ts,
                            parameter=param_name,
                            value=val,
                            anomaly_type=AnomalyType.SPIKE,
                            severity="高" if change_rate > 0.3 else "中",
                            description=f"{param_name}突变 (变化率: {change_rate*100:.1f}%)",
                            baseline_value=values[i-1],
                            deviation=change_rate
                        )

            # 3. 检测数据卡死
            if i >= 10:
                recent = values[i-10:i+1]
                if len(set(recent[~np.isnan(recent)])) <= 2:  # 最近11个值几乎相同
                    if anomaly is None:
                        anomaly = Anomaly(
                            timestamp=ts,
                            parameter=param_name,
                            value=val,
                            anomaly_type=AnomalyType.FROZEN,
                            severity="低",
                            description=f"{param_name}数据可能卡死 (连续相同值)",
                            baseline_value=mean_val,
                            deviation=0
                        )

            if anomaly:
                anomalies.append(anomaly)

        return anomalies

    def predict_alarms(self, history_data: Dict[str, pd.DataFrame],
                       prediction_window: int = 30) -> List[AlarmPrediction]:
        """
        预测可能发生的报警

        Args:
            history_data: 历史数据
            prediction_window: 预测窗口（分钟），用于估计报警时间
        """
        self.predictions = []

        if not self.baselines:
            self.calculate_baselines(history_data)

        for alarm_name, (param_name, direction) in self.alarm_parameter_mapping.items():
            if param_name not in history_data:
                continue

            df = history_data[param_name]
            thresholds = self.parameter_thresholds.get(param_name)
            if thresholds is None:
                continue

            normal_low, normal_high, alarm_low, alarm_high = thresholds

            # 取最近的数据点分析趋势
            recent_df = df.tail(20)
            if len(recent_df) < 5:
                continue

            values = recent_df['参数值'].values
            timestamps = recent_df['采集时间'].values

            # 计算趋势（线性回归斜率）
            x = np.arange(len(values))
            valid_mask = ~np.isnan(values)
            if valid_mask.sum() < 5:
                continue

            slope = np.polyfit(x[valid_mask], values[valid_mask], 1)[0]
            current_val = values[valid_mask][-1]
            last_ts = pd.to_datetime(timestamps[-1])

            # 判断是否趋向报警
            prediction = None

            if direction == 'lower':
                # 下限报警预测
                if slope < 0 and current_val < normal_low:
                    # 估计到达报警阈值的时间
                    if slope != 0:
                        steps_to_alarm = (alarm_low - current_val) / slope
                        if steps_to_alarm > 0 and steps_to_alarm < 100:
                            time_to_alarm = timedelta(minutes=5 * steps_to_alarm)
                            prob = min(0.9, 0.5 + 0.1 * (normal_low - current_val) / (normal_low - alarm_low + 1))

                            prediction = AlarmPrediction(
                                timestamp=last_ts,
                                predicted_alarm=alarm_name,
                                probability=prob,
                                estimated_time_to_alarm=time_to_alarm,
                                contributing_factors=[
                                    f"当前值 {current_val:.1f} 已低于正常范围 {normal_low}",
                                    f"下降趋势: {slope:.2f}/采样点"
                                ],
                                recommendation=f"建议检查{param_name}相关系统，防止继续下降"
                            )

            elif direction == 'upper':
                # 上限报警预测
                if slope > 0 and current_val > normal_high:
                    if slope != 0:
                        steps_to_alarm = (alarm_high - current_val) / slope
                        if steps_to_alarm > 0 and steps_to_alarm < 100:
                            time_to_alarm = timedelta(minutes=5 * steps_to_alarm)
                            prob = min(0.9, 0.5 + 0.1 * (current_val - normal_high) / (alarm_high - normal_high + 1))

                            prediction = AlarmPrediction(
                                timestamp=last_ts,
                                predicted_alarm=alarm_name,
                                probability=prob,
                                estimated_time_to_alarm=time_to_alarm,
                                contributing_factors=[
                                    f"当前值 {current_val:.1f} 已超过正常范围 {normal_high}",
                                    f"上升趋势: {slope:.2f}/采样点"
                                ],
                                recommendation=f"建议检查{param_name}相关系统，防止继续上升"
                            )

            if prediction:
                self.predictions.append(prediction)

        return self.predictions

    def get_anomaly_summary(self) -> pd.DataFrame:
        """获取异常汇总"""
        if not self.anomalies:
            return pd.DataFrame()

        summary_data = []
        for a in self.anomalies:
            summary_data.append({
                '时间': a.timestamp,
                '参数': a.parameter,
                '当前值': a.value,
                '异常类型': a.anomaly_type.value,
                '严重程度': a.severity,
                '描述': a.description
            })

        return pd.DataFrame(summary_data)

    def get_prediction_summary(self) -> pd.DataFrame:
        """获取预测汇总"""
        if not self.predictions:
            return pd.DataFrame()

        summary_data = []
        for p in self.predictions:
            summary_data.append({
                '检测时间': p.timestamp,
                '预测报警': p.predicted_alarm,
                '概率': f"{p.probability*100:.1f}%",
                '预计时间': str(p.estimated_time_to_alarm),
                '建议': p.recommendation
            })

        return pd.DataFrame(summary_data)


if __name__ == "__main__":
    from data_loader import DataLoader

    # 测试
    loader = DataLoader("/mnt/d/Projects/Task/chaowei")
    history = loader.load_history_data()

    detector = AnomalyDetector()
    detector.calculate_baselines(history)

    print("检测异常...")
    anomalies = detector.detect_anomalies(history)
    print(f"发现 {len(anomalies)} 个异常")

    summary = detector.get_anomaly_summary()
    if len(summary) > 0:
        print("\n异常汇总 (前20条):")
        print(summary.head(20).to_string())

    print("\n预测报警...")
    predictions = detector.predict_alarms(history)
    print(f"发现 {len(predictions)} 个潜在报警风险")

    pred_summary = detector.get_prediction_summary()
    if len(pred_summary) > 0:
        print("\n报警预测:")
        print(pred_summary.to_string())
