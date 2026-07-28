# cython: annotation_typing=False, infer_types=False, language_level=3
#!/usr/bin/env python3
"""
预测性维护系统 - 整合 Excel 点位说明与 PostgreSQL 数据

功能:
1. 根据设备ID自动加载对应点位的历史数据
2. 将 point_id 映射为中文参数名，与预测模块对接
3. 运行异常检测、健康看板、故障预测、能耗优化
4. 生成预测性维护报告

Usage:
    python predictive_maintenance.py                          # 默认分析正1#金帆球磨机
    python predictive_maintenance.py --device 102000000996    # 分析正2#衡远合膏机
    python predictive_maintenance.py --hours 48 --json        # 分析过去48小时并输出JSON
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .data_loader import DataLoader
from .anomaly_detector import AnomalyDetector
from .health_dashboard import HealthDashboard
from .fault_predictor import FaultPredictor
from .energy_optimizer import EnergyOptimizer
from .point_config import (
    get_device_config_for_predictor,
    get_device_name,
    DEVICES,
)


def _overlay_profile_thresholds(device_id: str, base: dict) -> dict:
    """用已确认参数画像的阈值覆盖硬编码 base（按中文名匹配）。任何失败都回退 base。"""
    try:
        from modules.device_param import param_profile
        from modules.device_param.services import TimescaleDB
    except Exception:
        return base
    db = TimescaleDB()
    if not db.connect():
        return base
    try:
        prof_thr = param_profile.get_threshold_config(db.conn, device_id)
        if prof_thr:
            merged = dict(base or {})
            merged.update(prof_thr)   # 画像优先覆盖同名参数
            print(f"[predictive_maintenance] {device_id} 用画像阈值覆盖 {len(prof_thr)} 个参数")
            return merged
    except Exception as e:
        print(f"[predictive_maintenance] 画像阈值覆盖失败，回退硬编码: {e}")
    finally:
        db.close()
    return base


class PredictiveMaintenance:
    """预测性维护分析器"""

    def __init__(self, device_id: str = "102000018415"):
        self.device_id = device_id
        self.device_name = get_device_name(device_id)
        self.config = get_device_config_for_predictor(device_id)
        self.loader = DataLoader()

        # 自动阈值：用"已确认参数画像"学到的阈值覆盖 point_config 硬编码（缺失则保留硬编码）。
        # 让新设备/未知参数零硬编码可用；失败/无画像一律回退，不破坏现状。
        self.config['thresholds'] = _overlay_profile_thresholds(
            device_id, self.config.get('thresholds', {}))

        # 初始化各分析模块，传入设备特定配置
        self.anomaly_detector = AnomalyDetector(config={
            'parameter_thresholds': self.config['thresholds'],
            'alarm_parameter_mapping': self.config['alarm_mapping'],
        })
        self.health_dashboard = HealthDashboard(config={
            'parameter_weights': self._build_parameter_weights(),
            'optimal_ranges': self._build_optimal_ranges(),
            'alarm_thresholds': self._build_alarm_thresholds(),
        })
        self.fault_predictor = FaultPredictor(config={
            'fault_patterns': self.config['fault_patterns'],
        })
        self.energy_optimizer = EnergyOptimizer(config={
            'power_thresholds': self._build_power_thresholds(),
            'optimal_conditions': self._build_optimal_conditions(),
            'filter_params': self._build_filter_params(),
        })

        self.results = {}
        self.history_data = None

    def _build_parameter_weights(self) -> dict:
        """构建参数权重（基于故障模式配置动态生成）"""
        weights = {}
        for pattern in self.config['fault_patterns'].values():
            for name in pattern.get('logic_names', []):
                weights[name] = 0.1
        # 功率/温度类参数权重更高
        for name in list(weights.keys()):
            if '功率' in name or '温度' in name:
                weights[name] = 0.15
        if '主机功率' in weights:
            weights['主机功率'] = 0.20
        # 归一化
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        return weights

    def _build_optimal_ranges(self) -> dict:
        """构建最优运行区间"""
        ranges = {}
        thresholds = self.config['thresholds']
        for name, (low, high, alarm_low, alarm_high) in thresholds.items():
            opt_val = (low + high) / 2
            ranges[name] = (low, opt_val, high)
        return ranges

    def _build_alarm_thresholds(self) -> dict:
        """构建报警阈值"""
        thresholds = {}
        for name, (low, high, alarm_low, alarm_high) in self.config['thresholds'].items():
            thresholds[name] = (alarm_low, alarm_high)
        return thresholds

    def _build_power_thresholds(self) -> dict:
        """构建功率/能耗阈值"""
        # 如果存在主机功率，使用球磨机的默认功率阈值
        if '主机功率' in self.config['thresholds']:
            return {
                'idle': 20,
                'normal_low': 95,
                'optimal_low': 100,
                'optimal_high': 105,
                'normal_high': 108,
                'overload': 110,
            }
        # 合膏机没有功率参数，返回通用阈值
        return {
            'idle': 5,
            'normal_low': 10,
            'optimal_low': 20,
            'optimal_high': 50,
            'normal_high': 60,
            'overload': 70,
        }

    def _build_optimal_conditions(self) -> dict:
        """构建最优工况参数"""
        conditions = {}
        for name, (low, high, alarm_low, alarm_high) in self.config['thresholds'].items():
            opt_low = low + (high - low) * 0.25
            opt_high = high - (high - low) * 0.25
            conditions[name] = (opt_low, opt_high)
        return conditions

    def _build_filter_params(self) -> list:
        """构建需要监控压差上升的参数"""
        params = []
        for pattern in self.config['fault_patterns'].values():
            if '过滤' in pattern.get('name', '') or '压差' in pattern.get('name', ''):
                params.extend(pattern.get('logic_names', []))
        return params if params else ['布袋压差', '过滤器压差']

    def load_data(self, hours: int = 24):
        """加载设备历史数据"""
        print(f"正在加载设备数据: {self.device_name} ({self.device_id})")
        self.history_data = self.loader.load_history_data(
            device_id=self.device_id,
            hours=hours,
            use_logic_names=True,
        )
        total_points = sum(len(df) for df in self.history_data.values())
        print(f"  已加载 {len(self.history_data)} 个参数, 共 {total_points} 条数据")
        for name, df in self.history_data.items():
            print(f"    - {name}: {len(df)} 条")

    def run_anomaly_detection(self) -> dict:
        """运行异常检测"""
        print("\n" + "=" * 60)
        print("  [1] 异常检测与报警预警")
        print("=" * 60)

        anomalies = self.anomaly_detector.detect_anomalies(self.history_data)
        predictions = self.anomaly_detector.predict_alarms(self.history_data)

        severity_counts = {"低": 0, "中": 0, "高": 0, "严重": 0}
        for a in anomalies:
            severity_counts[a.severity] += 1

        print(f"\n  检测到 {len(anomalies)} 个异常点")
        print(f"    严重: {severity_counts['严重']}, 高: {severity_counts['高']}, "
              f"中: {severity_counts['中']}, 低: {severity_counts['低']}")

        if predictions:
            print(f"\n  发现 {len(predictions)} 个潜在报警风险:")
            for p in predictions:
                print(f"    - {p.predicted_alarm}: {p.probability*100:.0f}% 概率")
                print(f"      预计时间: {p.estimated_time_to_alarm}")

        self.results['anomaly'] = {
            'total_anomalies': len(anomalies),
            'severity_distribution': severity_counts,
            'alarm_predictions': len(predictions),
            'details': self.anomaly_detector.get_anomaly_summary().to_dict('records') if anomalies else [],
        }
        return self.results['anomaly']

    def run_health_dashboard(self) -> dict:
        """运行健康看板"""
        print("\n" + "=" * 60)
        print("  [2] 设备健康看板")
        print("=" * 60)

        health = self.health_dashboard.evaluate_equipment(
            self.device_name, self.history_data
        )
        self.health_dashboard.print_dashboard()

        self.results['health'] = self.health_dashboard.get_dashboard_summary()
        return self.results['health']

    def run_fault_prediction(self) -> dict:
        """运行故障预测"""
        print("\n" + "=" * 60)
        print("  [3] 故障预测分析")
        print("=" * 60)

        predictions = self.fault_predictor.predict_faults(self.history_data)

        if predictions:
            print(self.fault_predictor.get_prediction_report())
        else:
            print("\n  当前未检测到明显的故障风险信号。")
            print("  设备运行状态良好。")

        self.results['fault'] = {
            'predictions': self.fault_predictor.get_prediction_summary().to_dict('records'),
        }
        return self.results['fault']

    def run_energy_optimization(self) -> dict:
        """运行能耗优化分析"""
        print("\n" + "=" * 60)
        print("  [4] 能耗优化分析")
        print("=" * 60)

        # 能耗分析需要功率数据，如果当前设备没有功率参数则跳过
        has_power = any('功率' in k for k in self.history_data.keys())
        if not has_power:
            print(f"\n  设备 {self.device_name} 无功率数据，跳过能耗分析")
            self.results['energy'] = {
                'skipped': True,
                'reason': '无功率数据',
            }
            return self.results['energy']

        try:
            metrics = self.energy_optimizer.analyze_energy(self.history_data)
            windows = self.energy_optimizer.find_optimal_windows(self.history_data)
            suggestions = self.energy_optimizer.generate_suggestions(self.history_data)
            print(self.energy_optimizer.get_energy_report())

            self.results['energy'] = {
                'metrics': {
                    'avg_power': metrics.avg_power,
                    'max_power': metrics.max_power,
                    'min_power': metrics.min_power,
                    'total_energy': metrics.total_energy,
                    'efficiency_score': metrics.efficiency_score,
                    'idle_time_ratio': metrics.idle_time_ratio,
                    'overload_time_ratio': metrics.overload_time_ratio,
                },
                'optimal_windows': [
                    {'start': w.start_time, 'end': w.end_time, 'efficiency': w.avg_efficiency}
                    for w in windows
                ],
                'suggestions': [
                    {
                        'category': s.category,
                        'description': s.description,
                        'potential_saving': s.potential_saving,
                        'priority': s.priority,
                    }
                    for s in suggestions
                ],
            }
        except Exception as e:
            print(f"  能耗分析出错: {e}")
            self.results['energy'] = {'error': str(e)}

        return self.results['energy']

    def run_all(self, hours: int = 24) -> dict:
        """运行完整预测性维护分析"""
        self.load_data(hours=hours)

        if not self.history_data:
            print("\n[错误] 未加载到任何数据，无法进行预测性维护分析")
            return {}

        self.run_anomaly_detection()
        self.run_health_dashboard()
        self.run_fault_prediction()
        self.run_energy_optimization()

        # 生成综合摘要
        print("\n" + "=" * 60)
        print("  [综合分析摘要]")
        print("=" * 60)

        health_score = self.results.get('health', {}).get('overall_score', 0)
        anomaly_count = self.results.get('anomaly', {}).get('total_anomalies', 0)
        fault_count = len(self.results.get('fault', {}).get('predictions', []))
        energy_score = self.results.get('energy', {}).get('metrics', {}).get('efficiency_score', 0)

        print(f"\n  设备: {self.device_name}")
        print(f"  设备健康指数: {health_score:.1f}/100")
        if energy_score:
            print(f"  能效评分: {energy_score:.1f}/100")
        print(f"  检测异常数: {anomaly_count}")
        print(f"  潜在故障风险: {fault_count}")

        print("\n  [优先处理事项]")
        priority_items = []
        if health_score < 70:
            priority_items.append("设备健康状况较差，建议尽快检修")
        if energy_score and energy_score < 75:
            priority_items.append("能效偏低，建议优化运行参数")
        if fault_count > 0:
            priority_items.append("存在潜在故障风险，建议预防性维护")

        severe = self.results.get('anomaly', {}).get('severity_distribution', {})
        if severe.get('严重', 0) + severe.get('高', 0) > 10:
            priority_items.append("高严重度异常较多，需要关注")

        if priority_items:
            for i, item in enumerate(priority_items, 1):
                print(f"    {i}. {item}")
        else:
            print("    设备运行状态良好，继续保持！")

        self.results['summary'] = {
            'timestamp': datetime.now().isoformat(),
            'device_id': self.device_id,
            'device_name': self.device_name,
            'health_score': health_score,
            'energy_score': energy_score,
            'anomaly_count': anomaly_count,
            'fault_risk_count': fault_count,
            'priority_items': priority_items,
        }

        return self.results

    def export_json(self, filepath: str = None):
        """导出JSON格式结果"""
        if filepath is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            filepath = f"predictive_maintenance_{self.device_id}_{ts}.json"

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n结果已导出到: {filepath}")


def main():
    parser = argparse.ArgumentParser(description='预测性维护系统')
    parser.add_argument('--device', default='102000018415',
                        help='设备ID (默认: 102000018415 正1#金帆球磨机)')
    parser.add_argument('--hours', type=int, default=24,
                        help='加载过去N小时的数据 (默认24)')
    parser.add_argument('--json', action='store_true', help='输出JSON格式结果')
    parser.add_argument('--output', help='JSON输出文件路径')
    args = parser.parse_args()

    device_id = args.device
    if device_id not in DEVICES:
        print(f"[错误] 未知设备ID: {device_id}")
        print(f"支持的设备: {list(DEVICES.keys())}")
        sys.exit(1)

    print("\n")
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║           预测性维护系统 v1.0                                  ║")
    print("  ║      Predictive Maintenance System                             ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print(f"\n  分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  设备: {get_device_name(device_id)} ({device_id})")
    print(f"  数据范围: 最近 {args.hours} 小时")

    pm = PredictiveMaintenance(device_id=device_id)
    pm.run_all(hours=args.hours)

    if args.json:
        pm.export_json(args.output)


if __name__ == "__main__":
    main()
