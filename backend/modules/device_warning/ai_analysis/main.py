# cython: annotation_typing=False, infer_types=False, language_level=3
#!/usr/bin/env python3
"""
工厂设备AI分析系统 - 主程序入口
Factory Equipment AI Analysis System

功能模块:
1. 异常检测与报警预警
2. 设备健康看板
3. 故障预测
4. 能耗优化分析

Usage:
    python main.py                    # 运行完整分析
    python main.py --module anomaly   # 仅运行异常检测
    python main.py --module health    # 仅运行健康看板
    python main.py --module fault     # 仅运行故障预测
    python main.py --module energy    # 仅运行能耗分析
    python main.py --json             # 输出JSON格式
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from .data_loader import DataLoader
from .anomaly_detector import AnomalyDetector
from .health_dashboard import HealthDashboard
from .fault_predictor import FaultPredictor
from .energy_optimizer import EnergyOptimizer


class FactoryAIAnalyzer:
    """工厂AI分析器 - 整合所有分析模块"""

    def __init__(self, data_dir: str = "."):
        self.data_dir = Path(data_dir)
        self.loader = DataLoader(data_dir)
        self.history_data = None
        self.alarm_definitions = None

        # 各分析模块
        self.anomaly_detector = AnomalyDetector()
        self.health_dashboard = HealthDashboard()
        self.fault_predictor = FaultPredictor()
        self.energy_optimizer = EnergyOptimizer()

        # 分析结果
        self.results = {}

    def load_data(self, hours: int = 24):
        """加载所有数据

        Args:
            hours: 加载过去N小时的数据
        """
        print("正在加载数据...")
        self.alarm_definitions = self.loader.load_alarm_definitions()
        self.history_data = self.loader.load_history_data(hours=hours)

        print(f"  已加载报警定义: {sum(len(df) for df in self.alarm_definitions.values())} 种报警类型")
        print(f"  已加载历史数据: {len(self.history_data)} 个参数")
        total_points = sum(len(df) for df in self.history_data.values())
        print(f"  总数据点数: {total_points}")

    def run_anomaly_detection(self) -> dict:
        """运行异常检测"""
        print("\n" + "="*70)
        print("  [1] 异常检测与报警预警")
        print("="*70)

        # 检测异常
        anomalies = self.anomaly_detector.detect_anomalies(self.history_data)
        predictions = self.anomaly_detector.predict_alarms(self.history_data)

        # 统计
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
                print(f"      建议: {p.recommendation}")

        # 显示最近的严重异常
        severe_anomalies = [a for a in anomalies if a.severity in ["高", "严重"]]
        if severe_anomalies:
            print(f"\n  最近的严重异常 (最后5条):")
            for a in severe_anomalies[-5:]:
                print(f"    [{a.timestamp}] {a.parameter}: {a.description}")

        self.results['anomaly'] = {
            'total_anomalies': len(anomalies),
            'severity_distribution': severity_counts,
            'alarm_predictions': len(predictions),
            'details': self.anomaly_detector.get_anomaly_summary().to_dict('records') if anomalies else []
        }

        return self.results['anomaly']

    def run_health_dashboard(self) -> dict:
        """运行健康看板分析"""
        print("\n" + "="*70)
        print("  [2] 设备健康看板")
        print("="*70)

        health = self.health_dashboard.evaluate_equipment("正1#金帆球磨机", self.history_data)
        self.health_dashboard.print_dashboard()

        self.results['health'] = self.health_dashboard.get_dashboard_summary()

        return self.results['health']

    def run_fault_prediction(self) -> dict:
        """运行故障预测"""
        print("\n" + "="*70)
        print("  [3] 故障预测分析")
        print("="*70)

        predictions = self.fault_predictor.predict_faults(self.history_data)

        if predictions:
            print(self.fault_predictor.get_prediction_report())
        else:
            print("\n  当前未检测到明显的故障风险信号。")
            print("  设备运行状态良好。")

        # 估计耗材剩余寿命
        features = self.fault_predictor.baselines
        print("\n  [耗材寿命估计]")

        remaining_bd = self.fault_predictor.estimate_remaining_life('布袋压差', features, 80)
        if remaining_bd:
            print(f"    布袋预计剩余寿命: {remaining_bd}")
        else:
            print(f"    布袋: 压差稳定，暂无更换需求")

        remaining_glq = self.fault_predictor.estimate_remaining_life('过滤器压差', features, 100)
        if remaining_glq:
            print(f"    过滤器预计剩余寿命: {remaining_glq}")
        else:
            print(f"    过滤器: 压差稳定，暂无更换需求")

        self.results['fault'] = {
            'predictions': self.fault_predictor.get_prediction_summary().to_dict('records'),
            'consumables': {
                '布袋': str(remaining_bd) if remaining_bd else "稳定",
                '过滤器': str(remaining_glq) if remaining_glq else "稳定"
            }
        }

        return self.results['fault']

    def run_energy_optimization(self) -> dict:
        """运行能耗优化分析"""
        print("\n" + "="*70)
        print("  [4] 能耗优化分析")
        print("="*70)

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
                'overload_time_ratio': metrics.overload_time_ratio
            },
            'optimal_windows': [
                {
                    'start': w.start_time,
                    'end': w.end_time,
                    'efficiency': w.avg_efficiency
                } for w in windows
            ],
            'suggestions': [
                {
                    'category': s.category,
                    'description': s.description,
                    'potential_saving': s.potential_saving,
                    'priority': s.priority
                } for s in suggestions
            ]
        }

        return self.results['energy']

    def run_all(self, hours: int = 24) -> dict:
        """运行所有分析

        Args:
            hours: 加载过去N小时的数据
        """
        self.load_data(hours=hours)

        self.run_anomaly_detection()
        self.run_health_dashboard()
        self.run_fault_prediction()
        self.run_energy_optimization()

        # 生成综合摘要
        print("\n" + "="*70)
        print("  [综合分析摘要]")
        print("="*70)

        health_score = self.results.get('health', {}).get('overall_score', 0)
        energy_score = self.results.get('energy', {}).get('metrics', {}).get('efficiency_score', 0)
        anomaly_count = self.results.get('anomaly', {}).get('total_anomalies', 0)
        fault_count = len(self.results.get('fault', {}).get('predictions', []))

        print(f"\n  设备健康指数: {health_score:.1f}/100")
        print(f"  能效评分: {energy_score:.1f}/100")
        print(f"  检测异常数: {anomaly_count}")
        print(f"  潜在故障风险: {fault_count}")

        # 综合建议
        print("\n  [优先处理事项]")
        priority_items = []

        if health_score < 70:
            priority_items.append("设备健康状况较差，建议尽快检修")
        if energy_score < 75:
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

        print("\n" + "="*70)

        self.results['summary'] = {
            'timestamp': datetime.now().isoformat(),
            'health_score': health_score,
            'energy_score': energy_score,
            'anomaly_count': anomaly_count,
            'fault_risk_count': fault_count,
            'priority_items': priority_items
        }

        return self.results

    def export_json(self, filepath: str = None):
        """导出JSON格式结果"""
        if filepath is None:
            filepath = self.data_dir / f"analysis_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n结果已导出到: {filepath}")


def main():
    parser = argparse.ArgumentParser(description='工厂设备AI分析系统')
    parser.add_argument('--data-dir', default='.',
                        help='数据目录路径')
    parser.add_argument('--module', choices=['anomaly', 'health', 'fault', 'energy', 'all'],
                        default='all', help='运行指定模块')
    parser.add_argument('--json', action='store_true', help='输出JSON格式结果')
    parser.add_argument('--output', help='JSON输出文件路径')
    parser.add_argument('--hours', type=int, default=24,
                        help='加载过去N小时的数据 (默认24)')

    args = parser.parse_args()

    print("\n")
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║           工厂设备AI分析系统 v1.0                              ║")
    print("  ║      Factory Equipment AI Analysis System                     ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print(f"\n  分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  数据范围: 最近 {args.hours} 小时")

    analyzer = FactoryAIAnalyzer(args.data_dir)

    if args.module == 'all':
        analyzer.run_all(hours=args.hours)
    else:
        analyzer.load_data(hours=args.hours)
        if args.module == 'anomaly':
            analyzer.run_anomaly_detection()
        elif args.module == 'health':
            analyzer.run_health_dashboard()
        elif args.module == 'fault':
            analyzer.run_fault_prediction()
        elif args.module == 'energy':
            analyzer.run_energy_optimization()

    if args.json:
        analyzer.export_json(args.output)


if __name__ == "__main__":
    main()
