# cython: annotation_typing=False, infer_types=False, language_level=3
"""
故障预测模块 - 基于机器学习的故障预测
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import warnings
warnings.filterwarnings('ignore')


class FaultType(Enum):
    """故障类型"""
    MECHANICAL = "机械故障"
    ELECTRICAL = "电气故障"
    THERMAL = "热管理故障"
    PRESSURE = "压力系统故障"
    MATERIAL = "物料系统故障"
    FILTER = "过滤系统故障"


@dataclass
class FaultPrediction:
    """故障预测结果"""
    fault_type: FaultType
    probability: float
    severity: str  # 轻微/中等/严重
    estimated_occurrence: timedelta
    related_parameters: List[str]
    warning_signs: List[str]
    preventive_actions: List[str]
    confidence: float
    fault_name: str = ""  # 具体的故障名称（支持配置化故障模式）


@dataclass
class PatternMatch:
    """模式匹配结果"""
    pattern_name: str
    match_score: float
    description: str


class FaultPredictor:
    """故障预测器"""

    # 故障模式定义：每种故障类型的特征参数变化模式
    FAULT_PATTERNS = {
        FaultType.THERMAL: {
            'description': '温度异常升高或下降',
            'parameters': ['前段温度', '中段温度', '后段温度', '铅粉温度'],
            'patterns': [
                {'name': '温度持续上升', 'condition': lambda trends: sum(t == '上升' for t in trends) >= 2},
                {'name': '温度波动异常', 'condition': lambda stds: any(s > 5 for s in stds)},
                {'name': '温差异常', 'condition': lambda vals: max(vals) - min(vals) > 20 if vals else False}
            ],
            'preventive_actions': [
                '检查冷却水系统',
                '检查热交换器',
                '验证温度传感器校准'
            ]
        },
        FaultType.PRESSURE: {
            'description': '风压系统异常',
            'parameters': ['正压风压', '负压风压'],
            'patterns': [
                {'name': '风压失衡', 'condition': lambda ratio: ratio > 3 or ratio < 1.5},
                {'name': '负压过低', 'condition': lambda vals: vals[1] < 180 if len(vals) > 1 else False},
                {'name': '正压过高', 'condition': lambda vals: vals[0] > 540 if vals else False}
            ],
            'preventive_actions': [
                '检查风机运行状态',
                '检查管道是否堵塞',
                '检查阀门开度'
            ]
        },
        FaultType.MECHANICAL: {
            'description': '机械部件异常',
            'parameters': ['主机功率'],
            'patterns': [
                {'name': '功率波动大', 'condition': lambda std: std > 5},
                {'name': '功率异常升高', 'condition': lambda val, baseline: val > baseline * 1.1},
                {'name': '功率异常降低', 'condition': lambda val, baseline: val < baseline * 0.85}
            ],
            'preventive_actions': [
                '检查轴承磨损',
                '检查传动系统',
                '检查润滑油状态',
                '检查电机状态'
            ]
        },
        FaultType.FILTER: {
            'description': '过滤系统堵塞',
            'parameters': ['布袋压差', '过滤器压差'],
            'patterns': [
                {'name': '压差持续上升', 'condition': lambda trends: all(t == '上升' for t in trends)},
                {'name': '压差过高', 'condition': lambda vals: any(v > 75 for v in vals)}
            ],
            'preventive_actions': [
                '清理或更换布袋',
                '清理或更换过滤器',
                '检查反吹系统'
            ]
        },
        FaultType.MATERIAL: {
            'description': '物料系统异常',
            'parameters': ['铅粒仓重量'],
            'patterns': [
                {'name': '物料消耗异常', 'condition': lambda rate: rate < 50 or rate > 200},
                {'name': '物料卡料', 'condition': lambda std: std < 100}
            ],
            'preventive_actions': [
                '检查进料系统',
                '检查振动器',
                '检查物料品质'
            ]
        }
    }

    def __init__(self, config: dict = None):
        self.predictions = []
        self.pattern_history = []
        self.baselines = {}
        self.config = config or {}
        self.fault_patterns = self.config.get('fault_patterns', self.FAULT_PATTERNS)

    def calculate_features(self, history_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict]:
        """计算特征用于故障预测"""
        features = {}

        for param_name, df in history_data.items():
            values = df['参数值'].dropna().values

            if len(values) < 10:
                continue

            # 基础统计
            recent = values[-20:] if len(values) >= 20 else values
            baseline = values[:-20] if len(values) > 40 else values[:len(values)//2]

            # 计算趋势
            x = np.arange(len(recent))
            slope = np.polyfit(x, recent, 1)[0]
            if slope > 0.1:
                trend = '上升'
            elif slope < -0.1:
                trend = '下降'
            else:
                trend = '稳定'

            # 计算变化率
            if len(values) >= 2:
                change_rates = np.diff(values) / (values[:-1] + 1e-6)
                max_change_rate = np.max(np.abs(change_rates[-10:])) if len(change_rates) >= 10 else 0
            else:
                max_change_rate = 0

            features[param_name] = {
                'current': recent[-1],
                'mean': np.mean(recent),
                'std': np.std(recent),
                'min': np.min(recent),
                'max': np.max(recent),
                'baseline_mean': np.mean(baseline) if len(baseline) > 0 else np.mean(recent),
                'baseline_std': np.std(baseline) if len(baseline) > 0 else np.std(recent),
                'trend': trend,
                'slope': slope,
                'max_change_rate': max_change_rate,
                'values': recent
            }

        self.baselines = features
        return features

    def detect_fault_patterns(self, features: Dict[str, Dict]) -> List[PatternMatch]:
        """检测故障模式（支持配置化）"""
        matches = []

        for pattern_key, pattern_def in self.fault_patterns.items():
            # 兼容旧配置和新配置
            params = pattern_def.get('parameters') or pattern_def.get('logic_names', [])
            if not params:
                continue

            relevant_features = {p: features[p] for p in params if p in features}
            if not relevant_features:
                continue

            match_score = 0
            matched_patterns = []
            thresholds = pattern_def.get('thresholds', {})
            fault_name = pattern_def.get('name', pattern_key.value if isinstance(pattern_key, FaultType) else str(pattern_key))

            # 通用检测逻辑
            trends = [f['trend'] for f in relevant_features.values()]
            stds = [f['std'] for f in relevant_features.values()]
            vals = [f['current'] for f in relevant_features.values()]
            current_vals = [f['current'] for f in relevant_features.values()]
            baseline_means = [f['baseline_mean'] for f in relevant_features.values()]

            # 1. 趋势检测：多个参数同时上升
            rise_count = thresholds.get('rise_count', 2)
            if sum(t == '上升' for t in trends) >= rise_count:
                match_score += 0.4
                matched_patterns.append('多参数持续上升')

            # 2. 波动检测
            std_max = thresholds.get('std_max', 5)
            if any(s > std_max for s in stds):
                match_score += 0.3
                matched_patterns.append('参数波动异常')

            # 3. 温差/压差检测
            diff_max = thresholds.get('diff_max')
            if diff_max and current_vals and max(current_vals) - min(current_vals) > diff_max:
                match_score += 0.3
                matched_patterns.append('参数间差异过大')

            # 4. 比值检测（如风压比）
            ratio_min = thresholds.get('ratio_min')
            ratio_max = thresholds.get('ratio_max')
            if ratio_min and ratio_max and len(current_vals) >= 2:
                # 尝试计算两个主要参数的比值
                ratio = current_vals[0] / (current_vals[1] + 1e-6)
                if ratio > ratio_max or ratio < ratio_min:
                    match_score += 0.5
                    matched_patterns.append('参数比值异常')

            # 5. 单项阈值检测
            neg_min = thresholds.get('neg_min')
            pos_max = thresholds.get('pos_max')
            if neg_min and any(v < neg_min for v in current_vals):
                match_score += 0.3
                matched_patterns.append('参数值过低')
            if pos_max and any(v > pos_max for v in current_vals):
                match_score += 0.3
                matched_patterns.append('参数值过高')

            # 6. 基线偏离检测
            rise_ratio = thresholds.get('rise_ratio', 1.1)
            drop_ratio = thresholds.get('drop_ratio', 0.85)
            for f in relevant_features.values():
                if f['current'] > f['baseline_mean'] * rise_ratio:
                    match_score += 0.3
                    matched_patterns.append('参数相对基线异常升高')
                    break
                if f['current'] < f['baseline_mean'] * drop_ratio:
                    match_score += 0.3
                    matched_patterns.append('参数相对基线异常降低')
                    break

            # 7. 压差类：持续上升
            if '压差' in fault_name:
                if trends and all(t == '上升' for t in trends):
                    match_score += 0.5
                    matched_patterns.append('压差持续上升')
                max_bd = thresholds.get('max_bd', 75)
                max_glq = thresholds.get('max_glq', 100)
                if any(v > max_bd for v in current_vals):
                    match_score += 0.4
                    matched_patterns.append('压差超过阈值')

            # 8. 物料类：消耗率检测
            if '物料' in fault_name or '重量' in fault_name:
                rate_min = thresholds.get('rate_min', 50)
                rate_max = thresholds.get('rate_max', 200)
                std_min = thresholds.get('std_min', 100)
                for f in relevant_features.values():
                    if len(f['values']) >= 2:
                        consumption_rate = abs(np.mean(np.diff(f['values'])))
                        if consumption_rate < rate_min or consumption_rate > rate_max:
                            match_score += 0.5
                            matched_patterns.append('物料变化速率异常')
                    if f['std'] < std_min:
                        match_score += 0.3
                        matched_patterns.append('物料变化过小(可能卡料)')

            # 9. 真空类
            if '真空' in fault_name:
                vac_min = thresholds.get('min', -90)
                vac_max = thresholds.get('max', -20)
                for v in current_vals:
                    if v < vac_min or v > vac_max:
                        match_score += 0.5
                        matched_patterns.append('真空度异常')
                        break

            if match_score > 0.3:
                matches.append(PatternMatch(
                    pattern_name=fault_name,
                    match_score=min(1.0, match_score),
                    description=f"检测到: {', '.join(matched_patterns[:3])}"
                ))

        return matches

    def predict_faults(self, history_data: Dict[str, pd.DataFrame]) -> List[FaultPrediction]:
        """预测可能发生的故障"""
        self.predictions = []

        # 计算特征
        features = self.calculate_features(history_data)

        # 检测故障模式
        pattern_matches = self.detect_fault_patterns(features)
        self.pattern_history.append({
            'timestamp': datetime.now(),
            'matches': pattern_matches
        })

        # 生成预测
        for match in pattern_matches:
            # 查找对应的故障模式定义
            pattern_def = None
            for pk, pd in self.fault_patterns.items():
                if pd.get('name') == match.pattern_name:
                    pattern_def = pd
                    break

            if pattern_def is None:
                # 尝试从默认配置查找
                for ft in FaultType:
                    if ft.value == match.pattern_name:
                        pattern_def = self.FAULT_PATTERNS.get(ft, {})
                        break

            if pattern_def is None:
                pattern_def = {}

            # 估计故障严重程度
            if match.match_score > 0.7:
                severity = "严重"
                est_time = timedelta(hours=2)
            elif match.match_score > 0.5:
                severity = "中等"
                est_time = timedelta(hours=8)
            else:
                severity = "轻微"
                est_time = timedelta(hours=24)

            # 收集相关参数的警告信号
            params = pattern_def.get('logic_names') or pattern_def.get('parameters', [])
            warning_signs = []
            for param in params:
                if param in features:
                    f = features[param]
                    if f['trend'] != '稳定':
                        warning_signs.append(f"{param}: {f['trend']}趋势")
                    if f['current'] > f['baseline_mean'] + 2*f['baseline_std']:
                        warning_signs.append(f"{param}: 当前值偏高")
                    if f['current'] < f['baseline_mean'] - 2*f['baseline_std']:
                        warning_signs.append(f"{param}: 当前值偏低")

            preventive_actions = pattern_def.get('preventive_actions', [
                '检查相关传感器和仪表',
                '检查设备运行状态',
                '联系维护人员排查',
            ])

            prediction = FaultPrediction(
                fault_type=FaultType.MECHANICAL,
                probability=match.match_score,
                severity=severity,
                estimated_occurrence=est_time,
                related_parameters=params,
                warning_signs=warning_signs,
                preventive_actions=preventive_actions,
                confidence=0.6 + 0.3 * match.match_score,
                fault_name=match.pattern_name,
            )

            self.predictions.append(prediction)

        # 按概率排序
        self.predictions.sort(key=lambda x: x.probability, reverse=True)

        return self.predictions

    def get_prediction_report(self) -> str:
        """生成预测报告"""
        if not self.predictions:
            return "当前未检测到明显的故障风险。"

        report = []
        report.append("="*70)
        report.append("  故障预测报告")
        report.append("  生成时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        report.append("="*70)

        for i, pred in enumerate(self.predictions, 1):
            name = pred.fault_name if pred.fault_name else pred.fault_type.value
            report.append(f"\n  [{i}] {name}")
            report.append(f"      概率: {pred.probability*100:.0f}%  严重程度: {pred.severity}")
            report.append(f"      预计发生时间: {pred.estimated_occurrence}")
            report.append(f"      置信度: {pred.confidence*100:.0f}%")

            report.append(f"      相关参数: {', '.join(pred.related_parameters)}")

            if pred.warning_signs:
                report.append("      预警信号:")
                for sign in pred.warning_signs[:3]:
                    report.append(f"        - {sign}")

            report.append("      建议措施:")
            for action in pred.preventive_actions[:3]:
                report.append(f"        * {action}")

        report.append("\n" + "="*70)
        return "\n".join(report)

    def get_prediction_summary(self) -> pd.DataFrame:
        """获取预测汇总DataFrame"""
        if not self.predictions:
            return pd.DataFrame()

        data = []
        for pred in self.predictions:
            data.append({
                '故障类型': pred.fault_name if pred.fault_name else pred.fault_type.value,
                '概率': f"{pred.probability*100:.0f}%",
                '严重程度': pred.severity,
                '预计时间': str(pred.estimated_occurrence),
                '置信度': f"{pred.confidence*100:.0f}%",
                '相关参数': ', '.join(pred.related_parameters),
                '首要建议': pred.preventive_actions[0] if pred.preventive_actions else ''
            })

        return pd.DataFrame(data)

    def estimate_remaining_life(self, param_name: str, features: Dict[str, Dict],
                                  threshold: float) -> Optional[timedelta]:
        """
        估计剩余寿命（到达阈值的时间）

        用于压差类参数，预测到达更换阈值的时间
        """
        if param_name not in features:
            return None

        f = features[param_name]
        current = f['current']
        slope = f['slope']

        if slope <= 0:
            return None  # 没有上升趋势，不需要预测

        # 假设每5分钟一个采样点
        steps_to_threshold = (threshold - current) / slope
        if steps_to_threshold <= 0:
            return timedelta(minutes=0)

        minutes_to_threshold = steps_to_threshold * 5
        # timedelta 最大约 2.9e8 分钟，超出则返回 None
        if minutes_to_threshold > 1e8:
            return None
        return timedelta(minutes=minutes_to_threshold)


if __name__ == "__main__":
    from data_loader import DataLoader

    # 测试
    loader = DataLoader("/mnt/d/Projects/Task/chaowei")
    history = loader.load_history_data()

    predictor = FaultPredictor()
    predictions = predictor.predict_faults(history)

    print(predictor.get_prediction_report())

    # 估计布袋剩余寿命
    features = predictor.baselines
    remaining = predictor.estimate_remaining_life('布袋压差', features, 80)
    if remaining:
        print(f"\n布袋预计剩余寿命: {remaining}")

    remaining = predictor.estimate_remaining_life('过滤器压差', features, 100)
    if remaining:
        print(f"过滤器预计剩余寿命: {remaining}")
