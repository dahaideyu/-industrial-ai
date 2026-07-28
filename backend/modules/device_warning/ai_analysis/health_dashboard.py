# cython: annotation_typing=False, infer_types=False, language_level=3
"""
设备健康看板模块 - 计算设备综合健康指数和状态展示
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class HealthStatus(Enum):
    """健康状态"""
    EXCELLENT = "优秀"    # 90-100
    GOOD = "良好"         # 75-89
    FAIR = "一般"         # 60-74
    WARNING = "警告"      # 40-59
    CRITICAL = "危险"     # 0-39


@dataclass
class ParameterHealth:
    """单参数健康状态"""
    name: str
    current_value: float
    health_score: float  # 0-100
    status: HealthStatus
    trend: str  # 上升/稳定/下降
    deviation_from_optimal: float
    risk_factors: List[str]


@dataclass
class EquipmentHealth:
    """设备整体健康状态"""
    equipment_name: str
    timestamp: datetime
    overall_score: float  # 0-100
    status: HealthStatus
    parameter_scores: Dict[str, ParameterHealth]
    top_risks: List[str]
    recommendations: List[str]


class HealthDashboard:
    """设备健康看板"""

    # 各参数的权重（重要性）
    PARAMETER_WEIGHTS = {
        '主机功率': 0.20,      # 核心参数
        '中段温度': 0.12,
        '后段温度': 0.12,
        '前段温度': 0.12,
        '负压风压': 0.10,
        '正压风压': 0.10,
        '铅粉温度': 0.08,
        '布袋压差': 0.06,
        '过滤器压差': 0.06,
        '铅粒仓重量': 0.04,    # 物料参数，影响较小
    }

    # 最优运行区间 (最优下限, 最优值, 最优上限)
    OPTIMAL_RANGES = {
        '铅粒仓重量': (20000, 27000, 35000),
        '中段温度': (200, 210, 220),
        '后段温度': (200, 210, 220),
        '前段温度': (200, 210, 220),
        '主机功率': (98, 103, 106),
        '负压风压': (200, 215, 225),
        '正压风压': (500, 520, 535),
        '铅粉温度': (100, 108, 115),
        '布袋压差': (50, 60, 70),
        '过滤器压差': (80, 88, 95)
    }

    # 报警阈值
    ALARM_THRESHOLDS = {
        '铅粒仓重量': (10000, 40000),
        '中段温度': (150, 230),
        '后段温度': (150, 230),
        '前段温度': (150, 230),
        '主机功率': (80, 110),
        '负压风压': (150, 250),
        '正压风压': (400, 550),
        '铅粉温度': (80, 120),
        '布袋压差': (30, 80),
        '过滤器压差': (60, 100)
    }

    def __init__(self, config: dict = None):
        self.current_health = None
        self.health_history = []
        self.config = config or {}
        self.parameter_weights = self.config.get('parameter_weights', self.PARAMETER_WEIGHTS)
        self.optimal_ranges = self.config.get('optimal_ranges', self.OPTIMAL_RANGES)
        self.alarm_thresholds = self.config.get('alarm_thresholds', self.ALARM_THRESHOLDS)

    def calculate_parameter_health(self, param_name: str, values: np.ndarray,
                                    timestamps: np.ndarray) -> ParameterHealth:
        """计算单个参数的健康分数"""
        if len(values) == 0 or param_name not in self.OPTIMAL_RANGES:
            return ParameterHealth(
                name=param_name,
                current_value=0,
                health_score=50,
                status=HealthStatus.FAIR,
                trend="未知",
                deviation_from_optimal=0,
                risk_factors=["数据不足"]
            )

        # 获取配置
        opt_low, opt_val, opt_high = self.optimal_ranges[param_name]
        alarm_low, alarm_high = self.alarm_thresholds[param_name]

        # 当前值（最近的有效值）
        valid_values = values[~np.isnan(values)]
        if len(valid_values) == 0:
            return ParameterHealth(
                name=param_name,
                current_value=0,
                health_score=50,
                status=HealthStatus.FAIR,
                trend="未知",
                deviation_from_optimal=0,
                risk_factors=["无有效数据"]
            )

        current_val = valid_values[-1]
        avg_val = np.mean(valid_values[-10:]) if len(valid_values) >= 10 else np.mean(valid_values)

        # 计算健康分数
        score = self._calculate_score(current_val, opt_low, opt_val, opt_high, alarm_low, alarm_high)

        # 计算趋势
        trend = self._calculate_trend(valid_values)

        # 计算偏离度
        deviation = abs(current_val - opt_val) / (opt_high - opt_low + 1e-6)

        # 识别风险因素
        risk_factors = []
        if current_val < opt_low:
            risk_factors.append(f"值偏低 (当前: {current_val:.1f}, 最优下限: {opt_low})")
        if current_val > opt_high:
            risk_factors.append(f"值偏高 (当前: {current_val:.1f}, 最优上限: {opt_high})")
        if current_val < alarm_low * 1.1:
            risk_factors.append(f"接近报警下限")
        if current_val > alarm_high * 0.9:
            risk_factors.append(f"接近报警上限")
        if trend == "下降" and current_val < opt_val:
            risk_factors.append("持续下降趋势")
        if trend == "上升" and current_val > opt_val:
            risk_factors.append("持续上升趋势")

        # 波动性检查
        if len(valid_values) >= 10:
            recent_std = np.std(valid_values[-10:])
            normal_range = opt_high - opt_low
            if recent_std > normal_range * 0.1:
                risk_factors.append(f"波动较大 (标准差: {recent_std:.1f})")

        # 确定状态
        status = self._score_to_status(score)

        return ParameterHealth(
            name=param_name,
            current_value=current_val,
            health_score=score,
            status=status,
            trend=trend,
            deviation_from_optimal=deviation,
            risk_factors=risk_factors
        )

    def _calculate_score(self, value: float, opt_low: float, opt_val: float,
                          opt_high: float, alarm_low: float, alarm_high: float) -> float:
        """计算健康分数 (0-100)"""
        # 在最优区间内：90-100分
        if opt_low <= value <= opt_high:
            # 越接近最优值分数越高
            if value <= opt_val:
                ratio = (value - opt_low) / (opt_val - opt_low + 1e-6)
            else:
                ratio = (opt_high - value) / (opt_high - opt_val + 1e-6)
            return 90 + 10 * min(1, ratio)

        # 在正常区间但不在最优区间：70-90分
        normal_low = (opt_low + alarm_low) / 2
        normal_high = (opt_high + alarm_high) / 2

        if normal_low <= value < opt_low:
            ratio = (value - normal_low) / (opt_low - normal_low + 1e-6)
            return 70 + 20 * ratio
        if opt_high < value <= normal_high:
            ratio = (normal_high - value) / (normal_high - opt_high + 1e-6)
            return 70 + 20 * ratio

        # 接近报警区间：40-70分
        if alarm_low <= value < normal_low:
            ratio = (value - alarm_low) / (normal_low - alarm_low + 1e-6)
            return 40 + 30 * ratio
        if normal_high < value <= alarm_high:
            ratio = (alarm_high - value) / (alarm_high - normal_high + 1e-6)
            return 40 + 30 * ratio

        # 超出报警范围：0-40分
        if value < alarm_low:
            ratio = max(0, value / alarm_low)
            return 40 * ratio
        if value > alarm_high:
            ratio = max(0, 2 - value / alarm_high)
            return 40 * ratio

        return 50  # 默认

    def _calculate_trend(self, values: np.ndarray) -> str:
        """计算趋势"""
        if len(values) < 5:
            return "数据不足"

        recent = values[-10:] if len(values) >= 10 else values
        x = np.arange(len(recent))
        slope = np.polyfit(x, recent, 1)[0]

        # 相对变化率
        change_rate = slope / (np.mean(recent) + 1e-6)

        if change_rate > 0.001:
            return "上升"
        elif change_rate < -0.001:
            return "下降"
        else:
            return "稳定"

    def _score_to_status(self, score: float) -> HealthStatus:
        """分数转状态"""
        if score >= 90:
            return HealthStatus.EXCELLENT
        elif score >= 75:
            return HealthStatus.GOOD
        elif score >= 60:
            return HealthStatus.FAIR
        elif score >= 40:
            return HealthStatus.WARNING
        else:
            return HealthStatus.CRITICAL

    def evaluate_equipment(self, equipment_name: str,
                           history_data: Dict[str, pd.DataFrame]) -> EquipmentHealth:
        """评估设备整体健康状态"""
        parameter_scores = {}
        weighted_sum = 0
        total_weight = 0
        all_risks = []

        for param_name, df in history_data.items():
            if param_name not in self.parameter_weights:
                continue

            weight = self.parameter_weights[param_name]
            values = df['参数值'].values
            timestamps = df['采集时间'].values

            param_health = self.calculate_parameter_health(param_name, values, timestamps)
            parameter_scores[param_name] = param_health

            weighted_sum += param_health.health_score * weight
            total_weight += weight

            # 收集风险
            for risk in param_health.risk_factors:
                all_risks.append(f"[{param_name}] {risk}")

        # 计算综合分数
        overall_score = weighted_sum / total_weight if total_weight > 0 else 50
        status = self._score_to_status(overall_score)

        # 按严重程度排序风险
        # 优先显示分数低的参数的风险
        sorted_params = sorted(parameter_scores.items(), key=lambda x: x[1].health_score)
        top_risks = []
        for param_name, param_health in sorted_params[:3]:
            if param_health.risk_factors:
                top_risks.extend([f"[{param_name}] {r}" for r in param_health.risk_factors[:2]])
        top_risks = top_risks[:5]  # 最多显示5个

        # 生成建议
        recommendations = self._generate_recommendations(parameter_scores, overall_score)

        self.current_health = EquipmentHealth(
            equipment_name=equipment_name,
            timestamp=datetime.now(),
            overall_score=overall_score,
            status=status,
            parameter_scores=parameter_scores,
            top_risks=top_risks,
            recommendations=recommendations
        )

        self.health_history.append(self.current_health)

        return self.current_health

    def _generate_recommendations(self, parameter_scores: Dict[str, ParameterHealth],
                                   overall_score: float) -> List[str]:
        """生成维护建议"""
        recommendations = []

        # 按分数排序，关注低分参数
        sorted_params = sorted(parameter_scores.items(), key=lambda x: x[1].health_score)

        for param_name, param_health in sorted_params:
            if param_health.health_score < 70:
                if "温度" in param_name:
                    if param_health.trend == "上升":
                        recommendations.append(f"检查{param_name}冷却系统，温度有上升趋势")
                    elif param_health.trend == "下降":
                        recommendations.append(f"检查{param_name}加热系统，温度有下降趋势")
                elif "功率" in param_name:
                    if param_health.current_value < self.optimal_ranges[param_name][0]:
                        recommendations.append("检查主机负载是否不足，功率偏低")
                    else:
                        recommendations.append("检查主机是否过载，功率偏高")
                elif "压差" in param_name:
                    if param_health.current_value > self.optimal_ranges[param_name][2]:
                        recommendations.append(f"建议清理或更换{param_name.replace('压差', '')}，压差偏高")
                elif "风压" in param_name:
                    recommendations.append(f"检查{param_name}相关风机和管道")

        # 整体建议
        if overall_score < 60:
            recommendations.insert(0, "设备健康状况较差，建议尽快安排全面检修")
        elif overall_score < 75:
            recommendations.insert(0, "建议在近期安排预防性维护")

        return recommendations[:5]  # 最多返回5条建议

    def get_dashboard_summary(self) -> Dict:
        """获取看板摘要数据"""
        if not self.current_health:
            return {}

        h = self.current_health

        # 参数状态统计
        status_counts = {"优秀": 0, "良好": 0, "一般": 0, "警告": 0, "危险": 0}
        param_list = []

        for name, ph in h.parameter_scores.items():
            status_counts[ph.status.value] += 1
            param_list.append({
                '参数': name,
                '当前值': f"{ph.current_value:.1f}",
                '健康分': f"{ph.health_score:.0f}",
                '状态': ph.status.value,
                '趋势': ph.trend
            })

        return {
            'equipment_name': h.equipment_name,
            'timestamp': h.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            'overall_score': round(h.overall_score, 1),
            'status': h.status.value,
            'status_icon': self._get_status_icon(h.status),
            'status_counts': status_counts,
            'parameters': param_list,
            'top_risks': h.top_risks,
            'recommendations': h.recommendations
        }

    def _get_status_icon(self, status: HealthStatus) -> str:
        """获取状态图标"""
        icons = {
            HealthStatus.EXCELLENT: "[OK]",
            HealthStatus.GOOD: "[OK]",
            HealthStatus.FAIR: "[--]",
            HealthStatus.WARNING: "[!!]",
            HealthStatus.CRITICAL: "[XX]"
        }
        return icons.get(status, "[??]")

    def print_dashboard(self):
        """打印看板"""
        summary = self.get_dashboard_summary()
        if not summary:
            print("暂无数据")
            return

        print("\n" + "="*70)
        print(f"  设备健康看板 - {summary['equipment_name']}")
        print(f"  更新时间: {summary['timestamp']}")
        print("="*70)

        # 综合评分
        score = summary['overall_score']
        bar_len = int(score / 2)
        bar = "#" * bar_len + "-" * (50 - bar_len)
        print(f"\n  综合健康指数: {score:.1f}/100 {summary['status_icon']} {summary['status']}")
        print(f"  [{bar}]")

        # 状态分布
        counts = summary['status_counts']
        print(f"\n  参数状态分布: 优秀:{counts['优秀']} 良好:{counts['良好']} "
              f"一般:{counts['一般']} 警告:{counts['警告']} 危险:{counts['危险']}")

        # 参数详情
        print("\n  各参数健康状态:")
        print("  " + "-"*66)
        print(f"  {'参数':<12} {'当前值':>10} {'健康分':>8} {'状态':<6} {'趋势':<6}")
        print("  " + "-"*66)
        for p in summary['parameters']:
            print(f"  {p['参数']:<12} {p['当前值']:>10} {p['健康分']:>8} {p['状态']:<6} {p['趋势']:<6}")

        # 风险提示
        if summary['top_risks']:
            print("\n  主要风险:")
            for risk in summary['top_risks']:
                print(f"    - {risk}")

        # 建议
        if summary['recommendations']:
            print("\n  维护建议:")
            for rec in summary['recommendations']:
                print(f"    * {rec}")

        print("\n" + "="*70)


if __name__ == "__main__":
    from data_loader import DataLoader

    # 测试
    loader = DataLoader("/mnt/d/Projects/Task/chaowei")
    history = loader.load_history_data()

    dashboard = HealthDashboard()
    health = dashboard.evaluate_equipment("正1#金帆球磨机", history)

    dashboard.print_dashboard()
