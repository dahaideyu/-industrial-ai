# cython: annotation_typing=False, infer_types=False, language_level=3
"""数据驱动的参数分组（按 p_name，跨设备复用）+ 组内派生特征。

分组来源：`_analyze_param_corr_groups.py` 对运行(code1)时段参数做 Spearman
相关 + 层次聚类，并在多台设备上交叉验证(2026-05-30)。**不是**来自 Excel/命名，
而是参数实际协同变化的相关性。详见 .wolf/cerebrum.md「数据驱动参数分组」。

关键结论(阈值 0.6，正2#/负2# 合膏机一致复现)：
  - 合膏「工艺核心耦合」组: 合膏温度 + 实时真空度 + 酸实时重量 + 铅实时重量
    (组内|corr| 0.73~0.81) —— point_config 把它们拆成温度/真空/称量三独立子系统，错。
  - Hs_Time / JS_Time 阶段计数器: 组内相关极高(0.94+)但是单调累加的**伪相关**，
    不纳入派生特征(只会让模型抓到"时间在走"而非工况)。
  - 球磨「风路」组: 正压风压 + 负压风压 + 过滤器压差 (0.75)。

派生特征只用**逐行**算子(比值/差/梯度/Real-Actual 偏差)，不含跨行统计，
因此对时序训练/测试切分**无泄漏**。
"""

import numpy as np
import pandas as pd


# ── 分组定义(按 p_name) ─────────────────────────────────────
# 合膏机(10 台参数名共通)
MIXER_GROUPS = {
    "core_process": [  # 工艺核心耦合(交叉验证最稳健)
        "Tec_Hg_tep", "Tec_Sszkd",
        "Tec_sour_Real_weight", "Tec_lead_Real_weight",
    ],
    "mix_temp": [  # 搅拌/加酸段温度簇
        "Tec_Sh1_tep", "Tec_Sh2_tep", "Tec_Sh3_tep",
        "Tec_Sh4_tep", "Tec_Sh5_tep", "Tec_Sh6_tep",
        "Tec_Js3_tep", "Tec_Js4_tep", "Tec_Js5_tep", "Tec_Js6_tep",
    ],
}
# Real ↔ Actual 称量配对(物理偏差 = 实时 - 实际)
MIXER_REAL_ACTUAL = [
    ("Tec_sour_Real_weight", "Tec_sour_Actual_weight"),
    ("Tec_lead_Real_weight", "Tec_lead_Actual_weight"),
    ("Tec_Water_Real_weight", "Tec_Water_Actual_weight"),
]

# 球磨机(参数体系完全不同)
BALL_MILL_GROUPS = {
    "air_path": ["Tec_Ffy", "Tec_Zfy", "Tec_Glq_Yc"],   # 风路系统(0.75)
    "stage_temp": ["Tec_Hd_Tep", "Tec_Zd_Tep", "Tec_Qd_Tep"],  # 段温度
}

# 伪相关、不纳入派生特征(仅文档/筛选用)
PSEUDO_CORR_PREFIXES = ("Tec_Hs", "Tec_JS")  # *_Time 阶段计数器


def detect_device_type(columns) -> str:
    """按存在的 p_name 判定设备类型。"""
    cols = set(columns)
    if "Tec_Hg_tep" in cols:        # 合膏温度 → 合膏机
        return "mixer"
    if "Tec_Power" in cols and "Tec_Ffy" in cols:   # 球磨机
        return "ball_mill"
    return "unknown"


def get_groups(device_type: str) -> dict:
    return {"mixer": MIXER_GROUPS, "ball_mill": BALL_MILL_GROUPS}.get(device_type, {})


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)


def build_group_features(df: pd.DataFrame) -> pd.DataFrame:
    """对原始参数宽表生成组内派生特征(前缀 grp__)。

    仅用原始参数列(无 '__' 的列)。逐行算子，无跨行统计 → 无切分泄漏。
    返回仅含新特征的 DataFrame(index 对齐 df)，便于 concat。
    """
    raw_cols = [c for c in df.columns if "__" not in c]
    present = set(raw_cols)
    dtype = detect_device_type(raw_cols)
    groups = get_groups(dtype)

    feats: dict[str, pd.Series] = {}

    # 1) 组内两两比值 + 差(组导向的交互，替代盲选 top-N)
    for gname, members in groups.items():
        m = [c for c in members if c in present]
        for i in range(len(m)):
            for j in range(i + 1, len(m)):
                a, b = m[i], m[j]
                feats[f"grp__{gname}__{a}_div_{b}"] = _safe_div(df[a], df[b])
                feats[f"grp__{gname}__{a}_sub_{b}"] = df[a] - df[b]
        # 组聚合：成员逐行均值/极差(同组量纲相近的温度簇有物理意义)
        if len(m) >= 2:
            sub = df[m]
            feats[f"grp__{gname}__row_mean"] = sub.mean(axis=1)
            feats[f"grp__{gname}__row_range"] = sub.max(axis=1) - sub.min(axis=1)

    # 2) 称量 Real - Actual 物理偏差(合膏机)
    if dtype == "mixer":
        for real, actual in MIXER_REAL_ACTUAL:
            if real in present and actual in present:
                tag = real.replace("Tec_", "").replace("_Real_weight", "")
                feats[f"grp__weigh_dev__{tag}"] = df[real] - df[actual]

    # 3) 球磨机物理关系：正负压比、温度梯度
    if dtype == "ball_mill":
        if "Tec_Zfy" in present and "Tec_Ffy" in present:
            feats["grp__air__pos_neg_ratio"] = _safe_div(df["Tec_Zfy"], df["Tec_Ffy"])
        if "Tec_Qd_Tep" in present and "Tec_Zd_Tep" in present:
            feats["grp__temp__grad_qd_zd"] = df["Tec_Qd_Tep"] - df["Tec_Zd_Tep"]
        if "Tec_Zd_Tep" in present and "Tec_Hd_Tep" in present:
            feats["grp__temp__grad_zd_hd"] = df["Tec_Zd_Tep"] - df["Tec_Hd_Tep"]

    if not feats:
        return pd.DataFrame(index=df.index)
    out = pd.DataFrame(feats, index=df.index)
    out = out.replace([np.inf, -np.inf], np.nan)
    return out


if __name__ == "__main__":
    # 自检：对一个 parquet 打印生成的组特征
    import sys
    from pathlib import Path
    p = sys.argv[1] if len(sys.argv) > 1 else \
        str(Path(__file__).resolve().parent.parent.parent /
            "features_output" / "features_102000000996.parquet")
    df = pd.read_parquet(p)
    g = build_group_features(df)
    print(f"设备类型: {detect_device_type([c for c in df.columns if '__' not in c])}")
    print(f"原始列: {df.shape[1]}  ->  生成组特征: {g.shape[1]}")
    for c in g.columns:
        print(f"  {c:<45} 非空率={g[c].notna().mean():.2f}")
