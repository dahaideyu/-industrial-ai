# cython: annotation_typing=False, infer_types=False, language_level=3
"""
故障预测服务 — 加载 XGBoost 模型 + LLM 解释

功能:
1. 加载训练好的 XGBoost 合并模型
2. 对新数据窗口进行故障概率预测
3. 提取 Top-N 关键特征
4. 调用 LLM 对故障风险进行语义解释
"""

import os
import pickle
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# 模型默认路径
DEFAULT_MODEL_PATH = Path(__file__).parent.parent.parent.parent.parent / \
    "features_output" / "models" / "combined" / "fault_predictor_best.pkl"


class FaultPredictor:
    """设备故障预测器"""

    def __init__(self, model_path: str = None):
        self._model = None
        self._feature_names = None
        self._model_type = None
        self._metrics = None
        self._load_model(model_path or str(DEFAULT_MODEL_PATH))

    def _load_model(self, model_path: str):
        if not os.path.exists(model_path):
            log.warning(f"模型文件不存在: {model_path}, 仅支持 LLM 模式")
            return

        with open(model_path, "rb") as f:
            data = pickle.load(f)

        self._model = data.get("model")
        self._model_type = data.get("model_type", "unknown")
        self._feature_names = data.get("feature_names", [])
        self._metrics = data.get("metrics", {})
        log.info(f"模型已加载: {self._model_type} "
                 f"(AUC={self._metrics.get('auc_roc', 'N/A'):.3f}) "
                 f"{len(self._feature_names)} 特征")

    @property
    def is_ready(self) -> bool:
        return self._model is not None

    @property
    def metrics(self) -> dict:
        return self._metrics or {}

    def predict(self, features: pd.DataFrame) -> pd.DataFrame:
        """
        对特征 DataFrame 进行故障预测

        Args:
            features: 特征 DataFrame，列需与训练时对齐

        Returns:
            DataFrame 包含: predict_time, fault_probability, is_risk,
                          top_features, top_feature_values
        """
        if not self.is_ready:
            return pd.DataFrame()

        # 对齐列
        X, aligned_df = self._align_features(features)

        # 预测
        proba = self._model.predict_proba(X)[:, 1]

        result = pd.DataFrame({
            "predict_time": features.index,
            "fault_probability": proba,
            "is_risk": proba > 0.5,
        }, index=features.index)

        # 提取每个高风险点的 Top-5 关键特征
        if hasattr(self._model, "feature_importances_"):
            result["top_features"] = result.apply(
                lambda r: self._explain_prediction(aligned_df.loc[r.name])
                if r["fault_probability"] > 0.3 else None, axis=1)

        return result

    def predict_latest(self, features: pd.DataFrame
                       ) -> Optional[Dict]:
        """
        预测最新一个时间点的故障风险

        Returns:
            {"fault_probability": float, "is_risk": bool, "top_features": [...]}
        """
        if features.empty:
            return None

        latest = features.iloc[[-1]]
        result = self.predict(latest)
        if result.empty:
            return None

        row = result.iloc[0]
        return {
            "predict_time": str(row["predict_time"]),
            "fault_probability": float(row["fault_probability"]),
            "is_risk": bool(row["is_risk"]),
            "risk_level": self._risk_level(row["fault_probability"]),
            "top_features": row.get("top_features"),
        }

    def _align_features(self, df: pd.DataFrame) -> Tuple[np.ndarray, pd.DataFrame]:
        """对齐特征列并填充缺失值，返回 (numpy_array, aligned_dataframe)"""
        common = [c for c in self._feature_names if c in df.columns]
        X = df[common].copy()

        # 缺失列填0
        for c in self._feature_names:
            if c not in X.columns:
                X[c] = 0.0

        X = X[self._feature_names]

        # 填充 NaN
        for col in X.columns:
            if X[col].isna().any():
                X[col] = X[col].fillna(X[col].mean() if not np.isnan(X[col].mean()) else 0)

        X = X.replace([np.inf, -np.inf], 0)
        aligned = X.copy()
        return X.values.astype(np.float64), aligned

    def _explain_prediction(self, feature_row: pd.Series
                            ) -> List[Dict]:
        """基于特征重要性解释单个预测（回退方案）"""
        if not hasattr(self._model, "feature_importances_"):
            return []

        imp = self._model.feature_importances_
        top_idx = np.argsort(imp)[::-1][:5]

        result = []
        for i in top_idx:
            name = self._feature_names[i]
            val = feature_row.get(name, np.nan)
            if pd.isna(val):
                continue
            result.append({
                "feature": name,
                "value": float(val) if not pd.isna(val) else None,
                "importance": float(imp[i]),
            })
        return result

    def explain_with_shap(self, features: pd.DataFrame
                          ) -> Dict:
        """
        SHAP 值解释：精确量化每个特征对故障预测的贡献

        Returns:
            {
                "base_value": 基线预测值,
                "shap_values": [{feature, value, shap_value, direction}, ...],
                "waterfall": [{feature, contribution}, ...]  # 瀑布图数据
            }
        """
        if not self.is_ready:
            return {"error": "模型未加载"}

        try:
            import shap
        except ImportError:
            return {"error": "SHAP 未安装: pip install shap"}

        X, _ = self._align_features(features)
        if X.shape[0] == 0:
            return {"error": "无有效特征数据"}

        try:
            explainer = shap.TreeExplainer(self._model)
        except Exception:
            # 回退到 KernelExplainer
            background = X[:min(50, X.shape[0])]
            explainer = shap.KernelExplainer(
                self._model.predict_proba, background)

        # 计算 SHAP 值
        shap_values = explainer.shap_values(X)

        # XGBoost 返回 (n_samples, n_features, 2) for binary
        if isinstance(shap_values, list):
            shap_values = shap_values[1]  # 正类(故障)的SHAP值
        elif shap_values.ndim == 3:
            shap_values = shap_values[:, :, 1]

        base_value = explainer.expected_value
        if isinstance(base_value, (list, np.ndarray)):
            base_value = float(base_value[1] if len(base_value) > 1 else base_value[0])
        else:
            base_value = float(base_value)

        # 对最新一个时间点做解释
        latest_shap = shap_values[-1]
        latest_features = features.iloc[-1]

        # 构建特征贡献列表
        contributions = []
        for i, shap_val in enumerate(latest_shap):
            if abs(shap_val) < 1e-6:
                continue
            name = self._feature_names[i] if i < len(self._feature_names) else f"f{i}"
            val = latest_features.get(name, np.nan)
            contributions.append({
                "feature": name,
                "value": float(val) if not (isinstance(val, float) and np.isnan(val)) else None,
                "shap_value": float(shap_val),
                "direction": "push_fault" if shap_val > 0 else "push_normal",
                "abs_impact": float(abs(shap_val)),
            })

        # 按绝对影响排序
        contributions.sort(key=lambda x: x["abs_impact"], reverse=True)

        # Top 特征（推动故障 & 抑制故障 分别取）
        push_fault = [c for c in contributions if c["direction"] == "push_fault"][:5]
        push_normal = [c for c in contributions if c["direction"] == "push_normal"][:5]

        # 瀑布图数据（top 10 by abs）
        waterfall = contributions[:10][::-1]

        return {
            "base_value": round(base_value, 6),
            "predicted_probability": float(self._model.predict_proba(X[-1:])[:, 1][0]),
            "top_push_fault": push_fault,
            "top_push_normal": push_normal,
            "waterfall": waterfall,
            "all_contributions": contributions[:20],
        }

    @staticmethod
    def _risk_level(prob: float) -> str:
        if prob < 0.1:
            return "low"
        elif prob < 0.3:
            return "medium"
        elif prob < 0.5:
            return "high"
        else:
            return "critical"


# ═══════════════════════════════════════════════════════════
# LLM 故障解释器
# ═══════════════════════════════════════════════════════════

FAULT_EXPLANATION_PROMPT = """你是一名工业设备预测性维护专家。以下是和膏机设备在最近时间窗口的传感器读数异常和模型预测结果。

## 设备信息
- 设备编码: {device_code}
- 设备名称: {device_name}

## 故障预测结果
- 故障概率: {fault_probability:.1%}
- 风险等级: {risk_level}

## 关键异常参数
{key_features}

## 历史告警上下文
{alarm_context}

请分析：
1. 这些参数异常的可能根因是什么？
2. 与和膏机常见故障模式（密封失效、温控异常、真空泄露、加料不均匀）的关联
3. 建议的排查和维修措施（按优先级排序）

用简洁专业的中文回答，200字以内。"""


def build_fault_explanation_prompt(
    device_code: str,
    device_name: str,
    prediction: Dict,
    status_context: str = ""
) -> str:
    """构建 LLM 故障解释 prompt"""
    key_features = ""
    for f in (prediction.get("top_features") or [])[:5]:
        key_features += f"- {f['feature']}: 当前值={f.get('value', 'N/A')}, 重要性权重={f['importance']:.4f}\n"

    if not key_features:
        key_features = "（模型未提取到关键特征）"

    risk_map = {"low": "低", "medium": "中", "high": "高", "critical": "严重"}
    risk_cn = risk_map.get(prediction.get("risk_level", "low"), "未知")

    return FAULT_EXPLANATION_PROMPT.format(
        device_code=device_code,
        device_name=device_name,
        fault_probability=prediction.get("fault_probability", 0),
        risk_level=risk_cn,
        key_features=key_features,
        alarm_context=status_context or "最近24小时内无历史告警记录",
    )


# 全局单例
_predictor: Optional[FaultPredictor] = None


def get_predictor(model_path: str = None) -> FaultPredictor:
    global _predictor
    if _predictor is None or model_path:
        _predictor = FaultPredictor(model_path)
    return _predictor
