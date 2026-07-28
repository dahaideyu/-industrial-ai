# cython: annotation_typing=False, infer_types=False, language_level=3
"""对比实验：在现有特征基础上叠加「数据驱动组派生特征」(grp__)，看预测提升。

复用 train_fault_predictor 的标签生成 / 时序切分 / 训练评估，仅在特征侧
加上 param_groups.build_group_features 产出的 grp__ 列。

baseline      = 现有 parquet 特征(rolling/diff/iact/alarm 等)
with_groups   = baseline + grp__ 组派生特征
groups_only   = 原始参数 + grp__ (剔除 rolling/iact 海量列，看可解释精简集)

标签(状态记录)缓存到 features_output/_label_cache/，抗 cntlm 隧道中断、二次秒回。

用法:
  PYTHONUTF8=1 PG_HOST=127.0.0.1 PG_PORT=15432 \
    backend/venv/Scripts/python.exe backend/tools/_compare_group_features.py [window]
"""
import sys
import time
import logging
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import train_fault_predictor as T
from param_groups import build_group_features

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("compare")
log.setLevel(logging.INFO)

FEATURES_DIR = HERE.parent.parent / "features_output"
LABEL_CACHE = FEATURES_DIR / "_label_cache"
LABEL_CACHE.mkdir(parents=True, exist_ok=True)
PRED_WINDOW = int(sys.argv[1]) if len(sys.argv) > 1 else 120


def fetch_labels_cached(numeric_id, start, end):
    """带 parquet 缓存 + 重试的状态记录获取（cntlm 隧道易断）。"""
    cache_f = LABEL_CACHE / f"status_{numeric_id}.parquet"
    if cache_f.exists():
        return pd.read_parquet(cache_f)
    last_err = None
    for attempt in range(4):
        try:
            df = T.fetch_labels(numeric_id, start, end)
            df.to_parquet(cache_f)
            return df
        except Exception as e:
            last_err = e
            log.warning(f"  fetch_labels({numeric_id}) 第{attempt+1}次失败: {str(e)[:60]}")
            time.sleep(2)
    raise last_err


def get_device_info_retry():
    for attempt in range(4):
        try:
            return T.get_device_info()
        except Exception as e:
            log.warning(f"get_device_info 第{attempt+1}次失败: {str(e)[:60]}")
            time.sleep(2)
    raise RuntimeError("get_device_info 多次失败")


def is_rolling_or_iact(col: str) -> bool:
    return ("__" in col and not col.startswith("grp__")) or col.startswith("iact__")


def load_combined(device_info, window, variant):
    """构造合并训练集。variant: baseline / with_groups / groups_only"""
    all_dfs = []
    total_alarms = 0
    for code, info in device_info.items():
        fpath = FEATURES_DIR / f"features_{code}.parquet"
        if not fpath.exists():
            continue
        feats = pd.read_parquet(fpath)
        raw_params = [c for c in feats.columns if "__" not in c
                      and not c.startswith(("alarm", "stop", "current", "min_since", "iact__"))]
        if len(raw_params) < 20:
            continue  # 跳过球磨机(11参数)，与基线 combine 口径一致

        if variant in ("with_groups", "groups_only"):
            g = build_group_features(feats)
            if not g.empty:
                feats = pd.concat([feats, g], axis=1)

        if variant == "groups_only":
            keep = [c for c in feats.columns if not is_rolling_or_iact(c)]
            feats = feats[keep]

        start, end = feats.index.min(), feats.index.max()
        status_df = fetch_labels_cached(info["numeric_id"], start, end)
        alarm_count = (status_df["status"] == 2).sum() if not status_df.empty else 0
        labels, drop_mask = T.generate_labels(
            feats.index, status_df, window, T.PURGE_WINDOW_MIN)
        feats["label"] = labels.values
        kept = feats[~drop_mask.values]
        all_dfs.append(kept)
        total_alarms += alarm_count

    if not all_dfs:
        return None, 0

    common = None
    for df in all_dfs:
        s = set(df.columns)
        common = s if common is None else (common & s)
    common = sorted(common)
    combined = pd.concat([df[common] for df in all_dfs], axis=0).sort_index()
    return combined, total_alarms


def run_variant(device_info, window, variant):
    combined, alarms = load_combined(device_info, window, variant)
    if combined is None or combined["label"].sum() < 20:
        log.warning(f"[{variant}] 数据不足")
        return None
    n_cols = len(combined.columns) - 1
    grp_cols = sum(1 for c in combined.columns if c.startswith("grp__"))

    import tempfile
    res = T.train_evaluate(combined, model_dir=tempfile.mkdtemp(),
                           prediction_window_min=window)
    if not res:
        log.warning(f"[{variant}] 训练跳过")
        return None
    best = T._pick_best(res)
    m = res[best]
    out = {
        "variant": variant, "model": best, "cols": n_cols, "grp_cols": grp_cols,
        "auc": m["auc_roc"], "precision": m["precision"],
        "recall": m["recall"], "f1": m["f1"],
        "top_feats": [f["feature"] for f in m.get("feature_importance", [])[:12]],
    }
    log.info(f"[{variant:<12}] cols={n_cols:<4}(grp={grp_cols:<3}) "
             f"AUC={out['auc']:.3f} P={out['precision']:.3f} "
             f"R={out['recall']:.3f} F1={out['f1']:.3f}  best={best}")
    return out


def main():
    device_info = get_device_info_retry()
    log.info(f"设备 {len(device_info)} 台 | 预测窗口 {PRED_WINDOW}min | "
             f"purge={T.PURGE_WINDOW_MIN} embargo={T.EMBARGO_MIN}")

    results = []
    for v in ("baseline", "with_groups", "groups_only"):
        r = run_variant(device_info, PRED_WINDOW, v)
        if r:
            results.append(r)

    print("\n" + "=" * 80)
    print(f"对比汇总 (合并训练, window={PRED_WINDOW}min)")
    print("=" * 80)
    print(f"{'variant':<13} {'cols':>5} {'grp':>4} {'AUC':>7} {'Prec':>7} {'Recall':>7} {'F1':>7}  model / delta")
    base = next((r for r in results if r["variant"] == "baseline"), None)
    for r in results:
        delta = ""
        if base and r is not base:
            delta = f"  dAUC={r['auc']-base['auc']:+.3f} dR={r['recall']-base['recall']:+.3f}"
        print(f"{r['variant']:<13} {r['cols']:>5} {r['grp_cols']:>4} "
              f"{r['auc']:>7.3f} {r['precision']:>7.3f} {r['recall']:>7.3f} {r['f1']:>7.3f}  "
              f"{r['model']}{delta}")

    print("\n--- with_groups Top12 重要特征 (★=组派生) ---")
    wg = next((r for r in results if r["variant"] == "with_groups"), None)
    if wg:
        for f in wg["top_feats"]:
            star = "★" if f.startswith("grp__") else " "
            print(f"  {star} {f}")


if __name__ == "__main__":
    main()
