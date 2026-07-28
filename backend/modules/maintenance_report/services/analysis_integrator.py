# cython: annotation_typing=False, infer_types=False, language_level=3
"""
分析整合服务 - 调用现有 AI 分析模块，整合结果
"""

import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import asdict
import pandas as pd

# 添加 AI 分析模块路径
_ai_analysis_path = Path(__file__).parent.parent.parent / "device_warning" / "ai_analysis"
if str(_ai_analysis_path) not in sys.path:
    sys.path.insert(0, str(_ai_analysis_path))

from modules.device_warning.ai_analysis.anomaly_detector import AnomalyDetector
from modules.device_warning.ai_analysis.health_dashboard import HealthDashboard
from modules.device_warning.ai_analysis.fault_predictor import FaultPredictor
from modules.device_warning.ai_analysis.point_config import get_device_config_for_predictor


class AnalysisIntegrator:
    """分析整合器 - 调用现有 AI 分析模块"""

    def __init__(self, device_id: str = None):
        self.device_id = device_id

        # 尝试获取设备特定配置
        config = None
        if device_id:
            try:
                config = get_device_config_for_predictor(device_id)
            except Exception:
                pass

        # 初始化分析模块
        self.anomaly_detector = AnomalyDetector()
        self.health_dashboard = HealthDashboard()
        self.fault_predictor = FaultPredictor(config)

    def analyze(self, history_data: Dict[str, pd.DataFrame]) -> Dict:
        """
        执行完整分析

        Args:
            history_data: 历史数据，按参数名分组的 DataFrame

        Returns:
            {
                "anomalies": List,
                "anomaly_summary": Dict,
                "alarm_predictions": List,
                "health": Dict,
                "fault_predictions": List,
                "summary": Dict
            }
        """
        result = {
            "anomalies": [],
            "anomaly_summary": {},
            "alarm_predictions": [],
            "health": None,
            "fault_predictions": [],
            "summary": {}
        }

        if not history_data:
            result["summary"] = self._empty_summary()
            return result

        try:
            # 1. 异常检测
            anomalies = self.anomaly_detector.detect_anomalies(history_data)
            alarm_predictions = self.anomaly_detector.predict_alarms(history_data)

            result["anomalies"] = self._convert_anomalies(anomalies)
            result["anomaly_summary"] = self._summarize_anomalies(anomalies)
            result["alarm_predictions"] = self._convert_alarm_predictions(alarm_predictions)
        except Exception as e:
            print(f"[警告] 异常检测失败: {e}")

        try:
            # 2. 健康评估
            device_name = self.device_id or "设备"
            health = self.health_dashboard.evaluate_equipment(device_name, history_data)
            result["health"] = self._convert_health(health)
        except Exception as e:
            print(f"[警告] 健康评估失败: {e}")

        try:
            # 3. 故障预测
            fault_predictions = self.fault_predictor.predict_faults(history_data)
            result["fault_predictions"] = self._convert_fault_predictions(fault_predictions)
        except Exception as e:
            print(f"[警告] 故障预测失败: {e}")

        # 4. 生成摘要
        result["summary"] = self._create_summary(result)

        return result

    def _convert_anomalies(self, anomalies: List) -> List[Dict]:
        """转换异常数据为字典"""
        return [
            {
                "parameter": a.parameter,
                "type": a.anomaly_type.value if hasattr(a.anomaly_type, 'value') else str(a.anomaly_type),
                "severity": a.severity,
                "value": a.value,
                "threshold": a.threshold,
                "description": a.description,
                "timestamp": a.timestamp.isoformat() if hasattr(a.timestamp, 'isoformat') else str(a.timestamp)
            }
            for a in anomalies
        ]

    def _summarize_anomalies(self, anomalies: List) -> Dict:
        """汇总异常统计"""
        severity_counts = {"低": 0, "中": 0, "高": 0, "严重": 0}
        type_counts = {}

        for a in anomalies:
            if a.severity in severity_counts:
                severity_counts[a.severity] += 1
            anomaly_type = a.anomaly_type.value if hasattr(a.anomaly_type, 'value') else str(a.anomaly_type)
            type_counts[anomaly_type] = type_counts.get(anomaly_type, 0) + 1

        return {
            "total": len(anomalies),
            "by_severity": severity_counts,
            "by_type": type_counts,
            "severe_count": severity_counts.get("严重", 0) + severity_counts.get("高", 0)
        }

    def _convert_alarm_predictions(self, predictions: List) -> List[Dict]:
        """转换报警预测为字典"""
        return [
            {
                "predicted_alarm": p.predicted_alarm,
                "probability": p.probability,
                "current_value": p.current_value,
                "threshold": p.threshold,
                "estimated_time_to_alarm": str(p.estimated_time_to_alarm) if p.estimated_time_to_alarm else None,
                "recommendation": p.recommendation
            }
            for p in predictions
        ]

    def _convert_health(self, health) -> Dict:
        """转换健康评估为字典"""
        if health is None:
            return None

        parameter_scores = {}
        if hasattr(health, 'parameter_scores') and health.parameter_scores:
            for param, score in health.parameter_scores.items():
                parameter_scores[param] = {
                    "health_score": score.health_score if hasattr(score, 'health_score') else score,
                    "status": score.status.value if hasattr(score, 'status') and hasattr(score.status, 'value') else str(getattr(score, 'status', 'unknown')),
                    "trend": getattr(score, 'trend', 'stable')
                }

        return {
            "overall_score": health.overall_score if hasattr(health, 'overall_score') else 0,
            "status": health.status.value if hasattr(health, 'status') and hasattr(health.status, 'value') else str(getattr(health, 'status', 'unknown')),
            "parameter_scores": parameter_scores,
            "top_risks": list(health.top_risks) if hasattr(health, 'top_risks') else [],
            "recommendations": list(health.recommendations) if hasattr(health, 'recommendations') else []
        }

    def _convert_fault_predictions(self, predictions: List) -> List[Dict]:
        """转换故障预测为字典"""
        return [
            {
                "fault_type": p.fault_type.value if hasattr(p.fault_type, 'value') else str(p.fault_type),
                "fault_name": p.fault_name if hasattr(p, 'fault_name') else "",
                "probability": p.probability,
                "severity": p.severity,
                "estimated_occurrence": str(p.estimated_occurrence) if p.estimated_occurrence else None,
                "related_parameters": list(p.related_parameters) if p.related_parameters else [],
                "warning_signs": list(p.warning_signs) if p.warning_signs else [],
                "preventive_actions": list(p.preventive_actions) if p.preventive_actions else [],
                "confidence": p.confidence if hasattr(p, 'confidence') else 0
            }
            for p in predictions
        ]

    def _create_summary(self, analysis_result: Dict) -> Dict:
        """创建分析摘要"""
        anomaly_summary = analysis_result.get("anomaly_summary", {})
        health = analysis_result.get("health", {})
        fault_predictions = analysis_result.get("fault_predictions", [])
        alarm_predictions = analysis_result.get("alarm_predictions", [])

        # 计算风险等级
        risk_level = "low"
        health_score = health.get("overall_score", 100) if health else 100
        severe_anomalies = anomaly_summary.get("severe_count", 0)
        high_risk_faults = len([f for f in fault_predictions if f.get("probability", 0) > 0.6])

        if health_score < 40 or high_risk_faults >= 2 or severe_anomalies >= 10:
            risk_level = "critical"
        elif health_score < 60 or high_risk_faults >= 1 or severe_anomalies >= 5:
            risk_level = "high"
        elif health_score < 75 or severe_anomalies >= 2:
            risk_level = "medium"

        # 收集维护建议
        maintenance_suggestions = []
        if health and health.get("recommendations"):
            maintenance_suggestions.extend(health["recommendations"][:5])
        for f in fault_predictions[:3]:
            if f.get("preventive_actions"):
                maintenance_suggestions.extend(f["preventive_actions"][:2])

        # 紧急行动
        urgent_actions = []
        if risk_level in ["critical", "high"]:
            if health_score < 60:
                urgent_actions.append("设备健康状况较差，建议安排检修")
            for f in fault_predictions:
                if f.get("probability", 0) > 0.7:
                    urgent_actions.append(f"高风险: {f.get('fault_name', f.get('fault_type', '未知故障'))}")
        for p in alarm_predictions:
            if p.get("probability", 0) > 0.8:
                urgent_actions.append(f"即将报警: {p.get('predicted_alarm', '未知报警')}")

        return {
            "total_anomalies": anomaly_summary.get("total", 0),
            "severe_anomalies": anomaly_summary.get("severe_count", 0),
            "health_score": health_score,
            "health_status": health.get("status", "unknown") if health else "unknown",
            "fault_count": len(fault_predictions),
            "high_risk_faults": high_risk_faults,
            "alarm_prediction_count": len(alarm_predictions),
            "risk_level": risk_level,
            "top_risks": health.get("top_risks", [])[:3] if health else [],
            "maintenance_suggestions": maintenance_suggestions[:5],
            "urgent_actions": urgent_actions[:3]
        }

    def _empty_summary(self) -> Dict:
        """返回空摘要"""
        return {
            "total_anomalies": 0,
            "severe_anomalies": 0,
            "health_score": 100,
            "health_status": "unknown",
            "fault_count": 0,
            "high_risk_faults": 0,
            "alarm_prediction_count": 0,
            "risk_level": "low",
            "top_risks": [],
            "maintenance_suggestions": [],
            "urgent_actions": []
        }

    def get_health_status_label(self, score: float) -> str:
        """获取健康状态标签"""
        if score >= 90:
            return "excellent"
        elif score >= 75:
            return "good"
        elif score >= 60:
            return "fair"
        elif score >= 40:
            return "warning"
        else:
            return "critical"

    def get_health_trend(
        self,
        current_score: float,
        previous_score: float
    ) -> str:
        """计算健康趋势"""
        diff = current_score - previous_score
        if diff > 5:
            return "up"
        elif diff < -5:
            return "down"
        else:
            return "stable"
