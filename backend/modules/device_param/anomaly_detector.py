# cython: annotation_typing=False, infer_types=False, language_level=3
"""
无监督异常检测 + 设备健康指数

方法:
  1. IQR 动态阈值 — 单参数统计过程控制，解释性强
  2. 孤立森林 (Isolation Forest) — 多参数联合异常检测，捕捉变量关系偏移
  3. 复合规则 — 参数异常 + PLC告警确认，降低误报
  4. 健康指数 (0-100) — 融合以上信号的综合评分

用法:
  detector = AnomalyDetector()
  detector.fit(normal_param_data, normal_features)
  result = detector.detect(current_features, current_param_data, alarm_events)
  # result.health_index, result.anomalies, result.iqr_violations, ...
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

log = logging.getLogger(__name__)


@dataclass
class IQRThreshold:
    """IQR 动态阈值"""
    param_name: str
    q1: float
    q3: float
    iqr: float
    lower: float   # Q1 - 1.5*IQR
    upper: float   # Q3 + 1.5*IQR
    lower_mild: float   # Q1 - 3*IQR (极端)
    upper_mild: float   # Q3 + 3*IQR (极端)
    median: float

    def score(self, value: float) -> float:
        """计算单值异常分: 0=正常, 1=极端异常"""
        if self.lower <= value <= self.upper:
            return 0.0
        if self.lower_mild <= value <= self.upper_mild:
            # 温和异常
            if value > self.upper:
                return (value - self.upper) / (self.upper_mild - self.upper) * 0.5 + 0.25
            else:
                return (self.lower - value) / (self.lower - self.lower_mild) * 0.5 + 0.25
        # 极端异常
        if value > self.upper_mild:
            return min(1.0, 0.5 + (value - self.upper_mild) / self.upper_mild * 0.5)
        return min(1.0, 0.5 + (self.lower_mild - value) / abs(self.lower_mild) * 0.5)


@dataclass
class AnomalyResult:
    """异常检测结果"""
    health_index: float                # 0-100 健康指数
    if_anomaly_score: float            # 孤立森林异常分 [0,1]
    iqr_violations: Dict[str, float]   # {param: violation_score}
    total_iqr_score: float             # IQR 综合分
    is_anomaly: bool                   # 是否判定为异常
    severity: str                      # normal/warning/critical
    contributing_params: List[str]     # 贡献最大的参数
    alarm_penalty: float               # 告警惩罚分


class AnomalyDetector:
    """无监督异常检测器"""

    def __init__(self, contamination: float = 0.05):
        self.contamination = contamination
        self._iqr_thresholds: Dict[str, IQRThreshold] = {}
        self._if_model: Optional[IsolationForest] = None
        self._scaler: Optional[StandardScaler] = None
        self._feature_names: List[str] = []
        self._is_fitted = False

    # ═══════════════════════════════════════════════════════
    # 训练
    # ═══════════════════════════════════════════════════════

    def fit(self, param_data: Dict[str, List[float]],
            features: Optional[pd.DataFrame] = None):
        """
        在正常数据上训练

        Args:
            param_data: {param_name: [values]} 正常时段的原始参数值
            features: 特征 DataFrame（窗口统计），用于训练孤立森林
        """
        # 1. IQR 阈值
        self._iqr_thresholds = {}
        for pname, values in param_data.items():
            clean = [v for v in values if v is not None and not np.isnan(v)]
            if len(clean) < 30:
                continue
            arr = np.array(clean)
            q1 = np.percentile(arr, 25)
            q3 = np.percentile(arr, 75)
            iqr = q3 - q1
            if iqr == 0:
                iqr = 1e-6
            self._iqr_thresholds[pname] = IQRThreshold(
                param_name=pname,
                q1=q1, q3=q3, iqr=iqr,
                lower=q1 - 1.5 * iqr,
                upper=q3 + 1.5 * iqr,
                lower_mild=q1 - 3.0 * iqr,
                upper_mild=q3 + 3.0 * iqr,
                median=np.median(arr),
            )
        log.info(f"IQR 阈值拟合: {len(self._iqr_thresholds)} 个参数")

        # 2. 孤立森林
        if features is not None and len(features) > 50:
            self._feature_names = list(features.columns)
            X = features.values.astype(np.float64)

            # 标准化
            self._scaler = StandardScaler()
            X_scaled = self._scaler.fit_transform(
                np.nan_to_num(X, nan=0, posinf=0, neginf=0))

            self._if_model = IsolationForest(
                contamination=self.contamination,
                random_state=42,
                n_estimators=200,
                max_samples=min(256, len(X)),
                n_jobs=-1,
            )
            self._if_model.fit(X_scaled)
            log.info(f"孤立森林拟合: {len(X)} 样本, {len(self._feature_names)} 特征")
        else:
            log.warning("特征数据不足，跳过孤立森林训练")

        self._is_fitted = True

    # ═══════════════════════════════════════════════════════
    # 检测
    # ═══════════════════════════════════════════════════════

    def detect(self,
               param_data: Dict[str, List[float]],
               features: Optional[pd.DataFrame] = None,
               alarm_events: Optional[List[Dict]] = None,
               timestamp: Optional[str] = None) -> AnomalyResult:
        """
        对单个时间点执行异常检测

        Returns:
            AnomalyResult 包含健康指数和异常详情
        """
        # 1. IQR 单参数检测
        iqr_violations = {}
        for pname, values in param_data.items():
            threshold = self._iqr_thresholds.get(pname)
            if threshold is None:
                continue
            val = values[-1] if isinstance(values, list) else values
            if val is None or np.isnan(val):
                continue
            score = threshold.score(val)
            if score > 0:
                iqr_violations[pname] = score

        total_iqr = max(iqr_violations.values()) if iqr_violations else 0.0

        # 2. 孤立森林
        if_score = 0.0
        if self._if_model is not None and features is not None and not features.empty:
            row = features.iloc[-1:] if len(features) > 1 else features
            common = [c for c in self._feature_names if c in row.columns]
            if common:
                X = row[common].values.astype(np.float64)
                X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)
                if self._scaler:
                    X = self._scaler.transform(X)
                raw = self._if_model.decision_function(X)[0]
                # decision_function: 正值=正常, 负值=异常. 映射到 [0,1]
                if_score = float(np.clip(-raw / 0.5, 0, 1))
                # 更好的映射：sigmoid
                if_score = float(1 / (1 + np.exp(raw * 2)))

        # 3. 告警惩罚
        alarm_penalty = 0.0
        if alarm_events:
            active_alarms = [a for a in alarm_events
                           if a.get("status") == 2]  # 报警
            if active_alarms:
                alarm_penalty = min(1.0, len(active_alarms) * 0.2)

        # 4. 健康指数 = 100 - 异常扣分
        # IQR 权重 0.3, IF 权重 0.5, 告警权重 0.2
        anomaly_score = total_iqr * 0.3 + if_score * 0.5 + alarm_penalty * 0.2
        health_index = max(0.0, min(100.0, 100 * (1 - anomaly_score)))

        # 5. 严重级别
        if anomaly_score > 0.6:
            severity = "critical"
            is_anomaly = True
        elif anomaly_score > 0.35:
            severity = "warning"
            is_anomaly = True
        else:
            severity = "normal"
            is_anomaly = False

        # 6. 关键贡献参数
        contributing = sorted(iqr_violations.items(),
                            key=lambda x: x[1], reverse=True)[:5]
        contributing_params = [p for p, _ in contributing]

        return AnomalyResult(
            health_index=round(health_index, 1),
            if_anomaly_score=round(if_score, 4),
            iqr_violations={k: round(v, 4) for k, v in iqr_violations.items()},
            total_iqr_score=round(total_iqr, 4),
            is_anomaly=is_anomaly,
            severity=severity,
            contributing_params=contributing_params,
            alarm_penalty=round(alarm_penalty, 4),
        )

    def detect_timeline(self,
                        param_series: Dict[str, pd.Series],
                        features: pd.DataFrame,
                        alarm_events: List[Dict] = None,
                        ) -> pd.DataFrame:
        """
        对整个时间线逐点检测

        Args:
            param_series: {p_name: pd.Series(index=timestamp, value=val)}
            features: 特征 DataFrame (index=timestamp)
            alarm_events: 告警事件列表

        Returns:
            DataFrame: index=timestamp, columns=[health_index, if_score, iqr_score, severity, is_anomaly, ...]
        """
        if features.empty:
            return pd.DataFrame()

        results = []
        for ts in features.index:
            # 提取该时间点的参数值
            point_params = {}
            for pname, series in param_series.items():
                if ts in series.index:
                    val = series[ts]
                    if not (val is None or (isinstance(val, float) and np.isnan(val))):
                        point_params[pname] = [val]

            # 提取特征行
            point_features = features.loc[[ts]] if ts in features.index else None

            # 该时间点的活跃告警
            active = []
            if alarm_events:
                ts_dt = ts if hasattr(ts, 'timestamp') else pd.Timestamp(ts)
                for ev in alarm_events:
                    s = ev.get("start_dt") or ev.get("start_time")
                    e = ev.get("end_dt") or ev.get("end_time")
                    if isinstance(s, str):
                        s = pd.Timestamp(s)
                    if e and isinstance(e, str):
                        e = pd.Timestamp(e)
                    if s and s <= ts_dt and (e is None or e >= ts_dt):
                        active.append(ev)

            result = self.detect(point_params, point_features, active)
            results.append({
                "timestamp": ts,
                "health_index": result.health_index,
                "if_anomaly_score": result.if_anomaly_score,
                "iqr_score": result.total_iqr_score,
                "alarm_penalty": result.alarm_penalty,
                "severity": result.severity,
                "is_anomaly": result.is_anomaly,
                "contributing_params": result.contributing_params,
            })

        return pd.DataFrame(results).set_index("timestamp")

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    def get_thresholds(self) -> Dict:
        """导出 IQR 阈值配置"""
        return {
            pname: {
                "q1": t.q1, "q3": t.q3, "iqr": t.iqr,
                "lower": t.lower, "upper": t.upper,
                "median": t.median,
            }
            for pname, t in self._iqr_thresholds.items()
        }


# 全局单例
_detector: Optional[AnomalyDetector] = None


def get_detector() -> AnomalyDetector:
    global _detector
    if _detector is None:
        _detector = AnomalyDetector()
    return _detector
