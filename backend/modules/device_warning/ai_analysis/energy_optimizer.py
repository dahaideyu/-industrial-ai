# cython: annotation_typing=False, infer_types=False, language_level=3
"""
能耗优化分析模块 - 分析功率消耗与产出效率
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class EnergyMetrics:
    """能耗指标"""
    avg_power: float           # 平均功率 kW
    max_power: float           # 最大功率 kW
    min_power: float           # 最小功率 kW
    power_std: float           # 功率标准差
    total_energy: float        # 总能耗 kWh
    efficiency_score: float    # 能效评分 0-100
    idle_time_ratio: float     # 空载时间比例
    overload_time_ratio: float # 过载时间比例


@dataclass
class OptimizationSuggestion:
    """优化建议"""
    category: str              # 建议类别
    description: str           # 建议描述
    potential_saving: float    # 潜在节能量 (kWh/天)
    saving_percentage: float   # 节能比例
    implementation: str        # 实施方式
    priority: str              # 优先级: 高/中/低


@dataclass
class OperatingWindow:
    """最佳运行窗口"""
    start_time: str
    end_time: str
    avg_efficiency: float
    characteristics: List[str]


class EnergyOptimizer:
    """能耗优化分析器"""

    # 功率阈值定义
    POWER_THRESHOLDS = {
        'idle': 20,           # 空载阈值
        'normal_low': 95,     # 正常运行下限
        'optimal_low': 100,   # 最优运行下限
        'optimal_high': 105,  # 最优运行上限
        'normal_high': 108,   # 正常运行上限
        'overload': 110       # 过载阈值
    }

    # 最优工况参数
    OPTIMAL_CONDITIONS = {
        '主机功率': (100, 105),
        '中段温度': (205, 215),
        '后段温度': (205, 215),
        '前段温度': (205, 215),
        '负压风压': (210, 225),
        '正压风压': (510, 530),
        '铅粉温度': (105, 112),
    }

    def __init__(self, config: dict = None):
        self.energy_metrics = None
        self.suggestions = []
        self.operating_windows = []
        self.config = config or {}
        self.power_thresholds = self.config.get('power_thresholds', self.POWER_THRESHOLDS)
        self.optimal_conditions = self.config.get('optimal_conditions', self.OPTIMAL_CONDITIONS)

    def analyze_energy(self, history_data: Dict[str, pd.DataFrame]) -> EnergyMetrics:
        """分析能耗数据"""
        if '主机功率' not in history_data:
            raise ValueError("缺少主机功率数据")

        power_df = history_data['主机功率']
        power_values = power_df['参数值'].dropna().values
        timestamps = power_df['采集时间'].dropna().values

        if len(power_values) == 0:
            raise ValueError("主机功率数据为空")

        # 基础统计
        avg_power = np.mean(power_values)
        max_power = np.max(power_values)
        min_power = np.min(power_values)
        power_std = np.std(power_values)

        # 计算总能耗 (假设5分钟采样间隔)
        sampling_interval_hours = 5 / 60
        total_energy = np.sum(power_values) * sampling_interval_hours

        # 计算空载时间比例
        idle_count = np.sum(power_values < self.power_thresholds['idle'])
        idle_time_ratio = idle_count / len(power_values)

        # 计算过载时间比例
        overload_count = np.sum(power_values > self.power_thresholds['overload'])
        overload_time_ratio = overload_count / len(power_values)

        # 计算效率评分
        efficiency_score = self._calculate_efficiency_score(
            power_values, history_data
        )

        self.energy_metrics = EnergyMetrics(
            avg_power=avg_power,
            max_power=max_power,
            min_power=min_power,
            power_std=power_std,
            total_energy=total_energy,
            efficiency_score=efficiency_score,
            idle_time_ratio=idle_time_ratio,
            overload_time_ratio=overload_time_ratio
        )

        return self.energy_metrics

    def _calculate_efficiency_score(self, power_values: np.ndarray,
                                      history_data: Dict[str, pd.DataFrame]) -> float:
        """计算能效评分"""
        score = 100.0

        # 1. 功率稳定性扣分 (波动大扣分)
        power_cv = np.std(power_values) / (np.mean(power_values) + 1e-6)
        if power_cv > 0.15:
            score -= 20 * (power_cv - 0.15) / 0.15
        elif power_cv > 0.1:
            score -= 10 * (power_cv - 0.1) / 0.05

        # 2. 空载时间扣分
        idle_ratio = np.sum(power_values < self.POWER_THRESHOLDS['idle']) / len(power_values)
        score -= idle_ratio * 30

        # 3. 过载时间扣分
        overload_ratio = np.sum(power_values > self.POWER_THRESHOLDS['overload']) / len(power_values)
        score -= overload_ratio * 25

        # 4. 最优区间运行时间加分
        optimal_low = self.power_thresholds['optimal_low']
        optimal_high = self.power_thresholds['optimal_high']
        optimal_ratio = np.sum((power_values >= optimal_low) & (power_values <= optimal_high)) / len(power_values)
        score += optimal_ratio * 10

        # 5. 工况协调性评估
        coordination_penalty = self._evaluate_condition_coordination(history_data)
        score -= coordination_penalty

        return max(0, min(100, score))

    def _evaluate_condition_coordination(self, history_data: Dict[str, pd.DataFrame]) -> float:
        """评估工况协调性，返回扣分值"""
        penalty = 0

        for param_name, (opt_low, opt_high) in self.optimal_conditions.items():
            if param_name not in history_data:
                continue

            values = history_data[param_name]['参数值'].dropna().values
            if len(values) == 0:
                continue

            # 计算不在最优区间的比例
            out_of_optimal = np.sum((values < opt_low) | (values > opt_high)) / len(values)
            penalty += out_of_optimal * 3  # 每个参数最多扣3分

        return min(15, penalty)  # 总共最多扣15分

    def find_optimal_windows(self, history_data: Dict[str, pd.DataFrame]) -> List[OperatingWindow]:
        """找出最佳运行时段"""
        self.operating_windows = []

        power_df = history_data['主机功率']
        power_values = power_df['参数值'].values
        timestamps = pd.to_datetime(power_df['采集时间'].values)

        # 按小时分组分析
        hourly_stats = {}
        for i, (ts, power) in enumerate(zip(timestamps, power_values)):
            if pd.isna(ts) or pd.isna(power):
                continue
            hour = ts.hour
            if hour not in hourly_stats:
                hourly_stats[hour] = {'powers': [], 'efficiency': []}

            # 计算该时刻的效率（功率在最优区间的程度）
            opt_low = self.POWER_THRESHOLDS['optimal_low']
            opt_high = self.POWER_THRESHOLDS['optimal_high']
            if opt_low <= power <= opt_high:
                efficiency = 100
            elif self.power_thresholds['normal_low'] <= power < opt_low:
                efficiency = 80 + 20 * (power - self.POWER_THRESHOLDS['normal_low']) / (opt_low - self.POWER_THRESHOLDS['normal_low'])
            elif opt_high < power <= self.power_thresholds['normal_high']:
                efficiency = 80 + 20 * (self.POWER_THRESHOLDS['normal_high'] - power) / (self.POWER_THRESHOLDS['normal_high'] - opt_high)
            else:
                efficiency = 60

            hourly_stats[hour]['powers'].append(power)
            hourly_stats[hour]['efficiency'].append(efficiency)

        # 找出高效时段
        hour_efficiency = []
        for hour, stats in hourly_stats.items():
            if len(stats['efficiency']) > 0:
                avg_eff = np.mean(stats['efficiency'])
                avg_power = np.mean(stats['powers'])
                hour_efficiency.append((hour, avg_eff, avg_power))

        hour_efficiency.sort(key=lambda x: x[1], reverse=True)

        # 合并连续的高效时段
        high_eff_hours = [h for h, e, p in hour_efficiency if e >= 85]

        if high_eff_hours:
            # 简单处理：取效率最高的时段
            best_start = min(high_eff_hours)
            best_end = max(high_eff_hours)
            avg_efficiency = np.mean([e for h, e, p in hour_efficiency if h in high_eff_hours])

            characteristics = []
            if best_start >= 22 or best_start <= 6:
                characteristics.append("夜间运行效率较高")
            if best_start >= 8 and best_end <= 18:
                characteristics.append("白班运行效率较高")

            self.operating_windows.append(OperatingWindow(
                start_time=f"{best_start:02d}:00",
                end_time=f"{(best_end+1)%24:02d}:00",
                avg_efficiency=avg_efficiency,
                characteristics=characteristics if characteristics else ["该时段工况稳定"]
            ))

        return self.operating_windows

    def generate_suggestions(self, history_data: Dict[str, pd.DataFrame]) -> List[OptimizationSuggestion]:
        """生成优化建议"""
        self.suggestions = []

        if self.energy_metrics is None:
            self.analyze_energy(history_data)

        metrics = self.energy_metrics

        # 1. 空载时间优化
        if metrics.idle_time_ratio > 0.05:
            daily_idle_hours = metrics.idle_time_ratio * 24
            potential_saving = daily_idle_hours * metrics.avg_power * 0.3  # 假设空载节省30%

            self.suggestions.append(OptimizationSuggestion(
                category="空载优化",
                description=f"设备空载时间占比 {metrics.idle_time_ratio*100:.1f}%，建议优化生产排程减少空转",
                potential_saving=potential_saving,
                saving_percentage=metrics.idle_time_ratio * 30,
                implementation="调整生产计划，减少设备空转等待时间；考虑设置自动休眠模式",
                priority="高" if metrics.idle_time_ratio > 0.1 else "中"
            ))

        # 2. 过载运行优化
        if metrics.overload_time_ratio > 0.02:
            self.suggestions.append(OptimizationSuggestion(
                category="负载均衡",
                description=f"设备过载运行时间占比 {metrics.overload_time_ratio*100:.1f}%，影响能效和设备寿命",
                potential_saving=metrics.overload_time_ratio * metrics.avg_power * 0.1,
                saving_percentage=metrics.overload_time_ratio * 10,
                implementation="优化进料速度；检查是否有机械阻力增加；考虑分散高峰负载",
                priority="高"
            ))

        # 3. 功率波动优化
        if metrics.power_std > 5:
            self.suggestions.append(OptimizationSuggestion(
                category="稳定运行",
                description=f"功率波动较大 (标准差: {metrics.power_std:.1f} kW)，建议改善运行稳定性",
                potential_saving=metrics.power_std * 0.5,
                saving_percentage=(metrics.power_std / metrics.avg_power) * 10,
                implementation="检查进料系统稳定性；优化PID控制参数；检查机械部件磨损",
                priority="中"
            ))

        # 4. 温度协调优化
        temp_params = ['前段温度', '中段温度', '后段温度']
        temp_values = []
        for param in temp_params:
            if param in history_data:
                vals = history_data[param]['参数值'].dropna().values
                if len(vals) > 0:
                    temp_values.append(np.mean(vals))

        if len(temp_values) == 3:
            temp_range = max(temp_values) - min(temp_values)
            if temp_range > 5:
                self.suggestions.append(OptimizationSuggestion(
                    category="温度优化",
                    description=f"各段温度差异较大 ({temp_range:.1f}°C)，可能影响产品质量和能效",
                    potential_saving=temp_range * 0.2,
                    saving_percentage=temp_range * 0.5,
                    implementation="检查各段加热/冷却系统；优化温度控制策略",
                    priority="中"
                ))

        # 5. 风压平衡优化
        if '正压风压' in history_data and '负压风压' in history_data:
            pos_press = np.mean(history_data['正压风压']['参数值'].dropna())
            neg_press = np.mean(history_data['负压风压']['参数值'].dropna())
            ratio = pos_press / (neg_press + 1e-6)

            if ratio < 2.0 or ratio > 2.8:
                self.suggestions.append(OptimizationSuggestion(
                    category="风压优化",
                    description=f"正负风压比 ({ratio:.2f}) 偏离最优值，影响粉尘收集效率",
                    potential_saving=abs(ratio - 2.4) * 2,
                    saving_percentage=abs(ratio - 2.4) * 3,
                    implementation="调整风机频率；检查管道密封性；优化阀门开度",
                    priority="低"
                ))

        # 6. 压差上升提醒
        filter_params = self.config.get('filter_params', ['布袋压差', '过滤器压差'])
        for param in filter_params:
            if param in history_data:
                df = history_data[param]
                values = df['参数值'].dropna().values
                if len(values) >= 20:
                    # 计算趋势
                    recent = values[-20:]
                    x = np.arange(len(recent))
                    slope = np.polyfit(x, recent, 1)[0]

                    if slope > 0.1:
                        current = recent[-1]
                        threshold = 80 if '布袋' in param else 100
                        steps_to_limit = (threshold - current) / slope if slope > 0 else 999

                        self.suggestions.append(OptimizationSuggestion(
                            category="维护提醒",
                            description=f"{param}呈上升趋势 (斜率: {slope:.2f}/采样点)，当前值: {current:.0f}",
                            potential_saving=5,  # 避免因堵塞导致的能耗增加
                            saving_percentage=2,
                            implementation=f"建议在约 {int(steps_to_limit * 5 / 60)} 小时内安排清理或更换",
                            priority="高" if steps_to_limit < 100 else "中"
                        ))

        # 按优先级和节能潜力排序
        priority_order = {"高": 0, "中": 1, "低": 2}
        self.suggestions.sort(key=lambda x: (priority_order[x.priority], -x.potential_saving))

        return self.suggestions

    def get_energy_report(self) -> str:
        """生成能耗分析报告"""
        if self.energy_metrics is None:
            return "请先运行能耗分析"

        m = self.energy_metrics
        report = []

        report.append("="*70)
        report.append("  能耗优化分析报告")
        report.append("  生成时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        report.append("="*70)

        report.append("\n  [能耗概况]")
        report.append(f"    平均功率: {m.avg_power:.1f} kW")
        report.append(f"    功率范围: {m.min_power:.1f} - {m.max_power:.1f} kW")
        report.append(f"    功率波动: {m.power_std:.1f} kW (标准差)")
        report.append(f"    总能耗: {m.total_energy:.1f} kWh")
        report.append(f"    能效评分: {m.efficiency_score:.1f}/100")

        report.append("\n  [运行状态分析]")
        report.append(f"    空载时间比例: {m.idle_time_ratio*100:.1f}%")
        report.append(f"    过载时间比例: {m.overload_time_ratio*100:.1f}%")
        optimal_ratio = 100 - (m.idle_time_ratio + m.overload_time_ratio) * 100
        report.append(f"    正常运行比例: {optimal_ratio:.1f}%")

        if self.operating_windows:
            report.append("\n  [最佳运行时段]")
            for window in self.operating_windows:
                report.append(f"    {window.start_time} - {window.end_time}")
                report.append(f"    平均效率: {window.avg_efficiency:.1f}%")
                for char in window.characteristics:
                    report.append(f"      - {char}")

        if self.suggestions:
            report.append("\n  [优化建议]")
            for i, sug in enumerate(self.suggestions, 1):
                report.append(f"\n    [{i}] {sug.category} (优先级: {sug.priority})")
                report.append(f"        {sug.description}")
                report.append(f"        潜在节能: {sug.potential_saving:.1f} kWh/天 ({sug.saving_percentage:.1f}%)")
                report.append(f"        实施方式: {sug.implementation}")

        # 计算总节能潜力
        total_saving = sum(s.potential_saving for s in self.suggestions)
        if total_saving > 0:
            report.append(f"\n  [节能潜力汇总]")
            report.append(f"    每日潜在节能: {total_saving:.1f} kWh")
            report.append(f"    每月潜在节能: {total_saving * 30:.0f} kWh")
            # 假设电价0.6元/kWh
            report.append(f"    每月节省电费: ¥{total_saving * 30 * 0.6:.0f}")

        report.append("\n" + "="*70)

        return "\n".join(report)


if __name__ == "__main__":
    from data_loader import DataLoader

    # 测试
    loader = DataLoader("/mnt/d/Projects/Task/chaowei")
    history = loader.load_history_data()

    optimizer = EnergyOptimizer()

    print("分析能耗数据...")
    metrics = optimizer.analyze_energy(history)

    print("查找最佳运行时段...")
    windows = optimizer.find_optimal_windows(history)

    print("生成优化建议...")
    suggestions = optimizer.generate_suggestions(history)

    print(optimizer.get_energy_report())
