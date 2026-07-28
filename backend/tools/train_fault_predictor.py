# cython: annotation_typing=False, infer_types=False, language_level=3
"""
设备故障预测模型训练 — 基于特征工程的机器学习 Pipeline

从 features_output/*.parquet 加载特征，从 TimescaleDB 获取状态标签，
训练 XGBoost / 随机森林二分类模型，预测未来 N 分钟内是否发生故障。

用法:
  # 单设备训练
  python train_fault_predictor.py --device_code 102000000996 --features ../features_output/features_102000000996.parquet

  # 所有设备汇总训练
  python train_fault_predictor.py --all_devices --features_dir ../features_output/

  # 自定义预测窗口
  python train_fault_predictor.py --device_code 102000000996 --features ... --prediction_window 30
"""

import sys, os, argparse, logging, json, pickle
from datetime import datetime, timedelta, date
from collections import defaultdict

import dotenv
import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (classification_report, roc_auc_score,
                              precision_recall_curve, confusion_matrix,
                              f1_score, precision_score, recall_score)
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler
try:
    import xgboost as xgb
    HAS_XGBOOST = True
except (ImportError, Exception):
    HAS_XGBOOST = False

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

PURGE_WINDOW_MIN = 15
EMBARGO_MIN = 60
DEFAULT_PREDICTION_WINDOWS = [60, 120, 240]
TEST_RATIO = 0.2


def _get_pg_config() -> dict:
    for env_path in [
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    ]:
        if os.path.exists(env_path):
            dotenv.load_dotenv(env_path)
            break
    dotenv.load_dotenv()
    return dict(
        host=os.getenv("PG_HOST", "127.0.0.1"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
        connect_timeout=20,
    )

PG = _get_pg_config()


def get_conn():
    return psycopg2.connect(**PG)


# ═══════════════════════════════════════════════════════════
# 标签生成
# ═══════════════════════════════════════════════════════════

def fetch_labels(device_id: int, start: datetime, end: datetime) -> pd.DataFrame:
    """获取设备告警记录作为标签源"""
    conn = get_conn()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT status, start_time, end_time
            FROM dev_device_status_record
            WHERE device_id = %s
              AND start_time >= %s AND start_time < %s
            ORDER BY start_time
        """, (device_id, start, end))
        rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["start_time"] = pd.to_datetime(df["start_time"])
    df["end_time"] = pd.to_datetime(df["end_time"])
    return df


def generate_labels(feature_index: pd.DatetimeIndex, status_df: pd.DataFrame,
                    prediction_window_min: int = 60,
                    purge_window_min: int = PURGE_WINDOW_MIN
                    ) -> tuple:
    """
    为每个特征时间点生成二分类标签 + 瞬态丢弃掩码

    返回 (labels, drop_mask):
      labels:    1 = 未来 (purge, prediction_window] 内发生报警;0 = 无报警
      drop_mask: True = 该样本距下次报警 ≤ purge_window 分钟,属故障前瞬态,应丢弃

    丢弃故障前瞬态样本可避免:
      - 把"接近故障的临界状态"误当作普通正例稀释信号
      - 推理时无法区分"早期预警"与"已进入故障过渡期"
    """
    n = len(feature_index)
    labels = np.zeros(n, dtype=int)
    drop_mask = np.zeros(n, dtype=bool)

    if status_df.empty:
        return (pd.Series(labels, index=feature_index, name="label"),
                pd.Series(drop_mask, index=feature_index, name="purge"))

    alarms = status_df[status_df["status"] == 2].copy()
    if alarms.empty:
        return (pd.Series(labels, index=feature_index, name="label"),
                pd.Series(drop_mask, index=feature_index, name="purge"))

    window = timedelta(minutes=prediction_window_min)
    purge = timedelta(minutes=purge_window_min)

    for i, ts in enumerate(feature_index):
        in_purge = alarms[(alarms["start_time"] > ts) &
                          (alarms["start_time"] <= ts + purge)]
        if not in_purge.empty:
            drop_mask[i] = True
            continue
        in_pred = alarms[(alarms["start_time"] > ts + purge) &
                         (alarms["start_time"] <= ts + window)]
        labels[i] = 1 if not in_pred.empty else 0

    return (pd.Series(labels, index=feature_index, name="label"),
            pd.Series(drop_mask, index=feature_index, name="purge"))


# ═══════════════════════════════════════════════════════════
# 模型训练
# ═══════════════════════════════════════════════════════════

def prepare_X_y(df: pd.DataFrame, fit_means: dict = None) -> tuple:
    """
    分离特征/标签 + 缺失值填充。

    fit_means=None: 计算并返回每列均值 (训练集模式)
    fit_means=<dict>: 使用提供的均值填充 (测试集模式),避免测试集统计量泄漏到训练
    """
    if "label" not in df.columns:
        raise ValueError("DataFrame 缺少 label 列")

    y = df["label"].values.astype(int)
    exclude = ["label"]
    feature_cols = [c for c in df.columns if c not in exclude]

    X = df[feature_cols].copy().replace([np.inf, -np.inf], np.nan)

    if fit_means is None:
        means = {}
        for col in X.columns:
            m = X[col].mean()
            means[col] = float(m) if not np.isnan(m) else 0.0
            X[col] = X[col].fillna(means[col])
    else:
        means = fit_means
        for col in X.columns:
            X[col] = X[col].fillna(means.get(col, 0.0))

    return X.values.astype(np.float64), y, feature_cols, means


def split_time_series(df: pd.DataFrame, test_ratio: float = TEST_RATIO,
                      embargo_min: int = EMBARGO_MIN) -> tuple:
    """
    时序划分:按 index 排序后,前 (1-test_ratio) 比例为训练集,
    跳过 embargo_min 分钟后的剩余为测试集。

    embargo 防止滑动窗口特征跨越切分边界造成的信息泄漏
    (本项目最大窗口 60min,默认 embargo=60min 即可保证窗口完全分离)。
    """
    df = df.sort_index()
    n = len(df)
    cut = max(1, int(n * (1 - test_ratio)))
    cut_ts = df.index[cut - 1]
    embargo_until = cut_ts + pd.Timedelta(minutes=embargo_min)

    train_df = df.iloc[:cut]
    test_df = df[df.index > embargo_until]

    return train_df, test_df, cut_ts, embargo_until


def train_evaluate(combined: pd.DataFrame, model_dir: str = "models",
                   embargo_min: int = EMBARGO_MIN,
                   prediction_window_min: int = None) -> dict:
    """训练 XGBoost 和 RandomForest,按时序划分训练/测试。"""
    train_df, test_df, cut_ts, embargo_until = split_time_series(
        combined, embargo_min=embargo_min)

    if len(train_df) < 100 or len(test_df) < 50:
        log.warning(f"切分后样本不足: train={len(train_df)} test={len(test_df)}, 跳过")
        return {}

    X_train, y_train, feature_names, means = prepare_X_y(train_df)
    X_test, y_test, _, _ = prepare_X_y(test_df, fit_means=means)

    pos_ratio = y_train.mean()
    log.info(f"时序切分: train={len(y_train):,} (≤ {cut_ts}) | "
             f"embargo={embargo_min}min | test={len(y_test):,} (> {embargo_until})")
    log.info(f"训练集正例率: {pos_ratio:.4f} ({y_train.sum()} pos / {len(y_train)})")
    log.info(f"测试集正例率: {y_test.mean():.4f} ({y_test.sum()} pos / {len(y_test)})")

    if y_train.sum() < 5 or y_test.sum() < 1:
        log.warning(f"训练/测试集正例不足 (train_pos={y_train.sum()}, test_pos={y_test.sum()}), 跳过")
        return {}

    scale_pos_weight = (1 - pos_ratio) / pos_ratio if pos_ratio > 0 else 1

    results = {}

    # ── XGBoost ──
    if HAS_XGBOOST:
        log.info("训练 XGBoost ...")
        xgb_model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            scale_pos_weight=scale_pos_weight,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
        )
        xgb_model.fit(X_train, y_train,
                      eval_set=[(X_test, y_test)],
                      verbose=False)

        xgb_pred = xgb_model.predict(X_test)
        xgb_proba = xgb_model.predict_proba(X_test)[:, 1]

        results["xgboost"] = {
            "model": xgb_model,
            "accuracy": float((xgb_pred == y_test).mean()),
            "precision": float(precision_score(y_test, xgb_pred, zero_division=0)),
            "recall": float(recall_score(y_test, xgb_pred, zero_division=0)),
            "f1": float(f1_score(y_test, xgb_pred, zero_division=0)),
            "auc_roc": float(roc_auc_score(y_test, xgb_proba)),
            "confusion_matrix": confusion_matrix(y_test, xgb_pred).tolist(),
            "feature_importance": _get_top_features(xgb_model, feature_names),
        }

        log.info(f"  XGBoost  AUC-ROC: {results['xgboost']['auc_roc']:.3f}  "
                 f"F1: {results['xgboost']['f1']:.3f}  "
                 f"Prec: {results['xgboost']['precision']:.3f}  "
                 f"Recall: {results['xgboost']['recall']:.3f}")
    else:
        log.warning("XGBoost 不可用 (libomp 缺失), 跳过")

    # ── RandomForest ──
    log.info("训练 RandomForest ...")
    rf_model = RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    rf_model.fit(X_train, y_train)

    rf_pred = rf_model.predict(X_test)
    rf_proba = rf_model.predict_proba(X_test)[:, 1]

    results["random_forest"] = {
        "model": rf_model,
        "accuracy": float((rf_pred == y_test).mean()),
        "precision": float(precision_score(y_test, rf_pred, zero_division=0)),
        "recall": float(recall_score(y_test, rf_pred, zero_division=0)),
        "f1": float(f1_score(y_test, rf_pred, zero_division=0)),
        "auc_roc": float(roc_auc_score(y_test, rf_proba)),
        "confusion_matrix": confusion_matrix(y_test, rf_pred).tolist(),
        "feature_importance": _get_top_features(rf_model, feature_names),
    }

    log.info(f"  RF       AUC-ROC: {results['random_forest']['auc_roc']:.3f}  "
             f"F1: {results['random_forest']['f1']:.3f}  "
             f"Prec: {results['random_forest']['precision']:.3f}  "
             f"Recall: {results['random_forest']['recall']:.3f}")

    # ── 保存最佳模型 ──
    os.makedirs(model_dir, exist_ok=True)

    xgb_auc = results.get("xgboost", {}).get("auc_roc", -1)
    rf_auc = results.get("random_forest", {}).get("auc_roc", -1)
    best = "xgboost" if xgb_auc >= rf_auc else "random_forest"
    best_model = results[best]["model"]

    split_meta = {
        "split_type": "time_series",
        "cut_timestamp": str(cut_ts),
        "embargo_min": embargo_min,
        "embargo_until": str(embargo_until),
        "train_size": int(len(y_train)),
        "test_size": int(len(y_test)),
        "train_pos_rate": float(pos_ratio),
        "test_pos_rate": float(y_test.mean()),
        "prediction_window_min": prediction_window_min,
        "purge_window_min": PURGE_WINDOW_MIN,
    }

    model_path = os.path.join(model_dir, "fault_predictor_best.pkl")
    with open(model_path, "wb") as f:
        pickle.dump({
            "model": best_model,
            "model_type": best,
            "feature_names": [str(fn) for fn in feature_names],
            "feature_means": means,
            "metrics": {k: v for k, v in results[best].items()
                       if k not in ("model", "feature_importance")},
            "split": split_meta,
        }, f)
    log.info(f"最佳模型 ({best}) 已保存: {model_path}")

    report = {
        "best_model": best,
        "split": split_meta,
    }
    for model_name in results:
        report[model_name] = {k: v for k, v in results[model_name].items()
                              if k not in ("model", "feature_importance")}
    report_path = os.path.join(model_dir, "evaluation_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log.info(f"评估报告已保存: {report_path}")

    return results


def _get_top_features(model, feature_names, top_n=20):
    if hasattr(model, "feature_importances_"):
        imp = model.feature_importances_
    else:
        return []

    idx = np.argsort(imp)[::-1][:top_n]
    return [{"feature": str(feature_names[i]), "importance": float(imp[i])}
            for i in idx]


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def get_device_info() -> dict:
    """获取所有设备 {device_code: numeric_id}"""
    conn = get_conn()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, device_id AS code, device_name FROM device_info ORDER BY id")
        devices = {r["code"]: {"numeric_id": r["id"], "name": r["device_name"]}
                   for r in cur.fetchall()}
    conn.close()
    return devices


def process_device(device_code: str, numeric_id: int, device_name: str,
                   features_path: str, prediction_window_min: int,
                   model_dir: str) -> dict:
    """处理单台设备: 加载特征 → 生成标签 → 丢弃瞬态 → 时序训练"""
    log.info(f"===== {device_code} ({device_name}) "
             f"window={prediction_window_min}min =====")

    if not os.path.exists(features_path):
        log.warning(f"特征文件不存在: {features_path}")
        return {}

    features = pd.read_parquet(features_path)
    log.info(f"加载特征: {len(features):,} 行 × {len(features.columns)} 列")

    start = features.index.min()
    end = features.index.max()
    status_df = fetch_labels(numeric_id, start, end)

    alarm_count = (status_df["status"] == 2).sum() if not status_df.empty else 0
    log.info(f"状态记录: {len(status_df):,} 条, 告警: {alarm_count:,} 条")

    labels, drop_mask = generate_labels(
        features.index, status_df, prediction_window_min, PURGE_WINDOW_MIN)
    features["label"] = labels.values

    kept = features[~drop_mask.values]
    log.info(f"标签分布: 正例={labels.sum():,}, 负例={(labels == 0).sum() - drop_mask.sum():,}, "
             f"瞬态丢弃={int(drop_mask.sum()):,} ({drop_mask.mean():.3f})")

    if kept["label"].sum() < 10:
        log.warning(f"告警样本太少 ({kept['label'].sum()}), 跳过训练")
        return {}

    try:
        return train_evaluate(kept, model_dir,
                              prediction_window_min=prediction_window_min)
    except Exception as e:
        log.error(f"训练失败: {e}", exc_info=True)
        return {}


def process_combined(device_info: dict, features_dir: str,
                     prediction_window_min: int, model_dir: str) -> dict:
    """合并所有设备特征,丢弃故障前瞬态后训练统一模型 (时序划分)"""
    log.info(f"===== 合并训练模式: {len(device_info)} 台设备, "
             f"window={prediction_window_min}min =====")

    all_features = []
    total_alarms = 0
    total_purged = 0

    for code, info in device_info.items():
        fpath = os.path.join(features_dir, f"features_{code}.parquet")
        if not os.path.exists(fpath):
            log.warning(f"跳过 {code}: 特征文件不存在")
            continue

        features = pd.read_parquet(fpath)
        raw_params = [c for c in features.columns
                      if "__" not in c
                      and not c.startswith(("alarm", "stop", "current", "min_since", "iact__"))]
        if len(raw_params) < 20:
            log.warning(f"跳过 {code}: 原始参数太少 ({len(raw_params)} 个)")
            continue

        start = features.index.min()
        end = features.index.max()
        status_df = fetch_labels(info["numeric_id"], start, end)

        alarm_count = (status_df["status"] == 2).sum() if not status_df.empty else 0
        labels, drop_mask = generate_labels(
            features.index, status_df, prediction_window_min, PURGE_WINDOW_MIN)

        features["label"] = labels.values
        kept = features[~drop_mask.values]
        purged = int(drop_mask.sum())

        all_features.append(kept)
        total_alarms += alarm_count
        total_purged += purged
        log.info(f"  {code}: kept={len(kept):,} (purged={purged}), "
                 f"告警={alarm_count}, 正例={int(kept['label'].sum())}")

    if not all_features:
        log.warning("无可用设备")
        return {}

    common_cols = None
    for df in all_features:
        cols = set(df.columns)
        if common_cols is None:
            common_cols = cols
        else:
            common_cols &= cols

    if "label" not in common_cols:
        log.error("label 列缺失")
        return {}
    common_cols_list = sorted(common_cols)
    log.info(f"合并列数: {len(common_cols_list)}")

    aligned = [df[common_cols_list] for df in all_features]
    combined = pd.concat(aligned, axis=0).sort_index()

    pos_rate = combined["label"].mean()
    log.info(f"合并数据: {len(combined):,} 行 × {len(combined.columns)} 列, "
             f"正例率: {pos_rate:.4f}, 告警总数: {total_alarms}, 瞬态丢弃: {total_purged:,}")

    if combined["label"].sum() < 20:
        log.warning(f"正例太少 ({combined['label'].sum()}), 无法训练")
        return {}

    return train_evaluate(combined, model_dir,
                          prediction_window_min=prediction_window_min)


def main():
    parser = argparse.ArgumentParser(description="设备故障预测模型训练")
    parser.add_argument("--device_code", default=None)
    parser.add_argument("--all_devices", action="store_true")
    parser.add_argument("--features", default=None,
                        help="单设备特征文件路径 (.parquet)")
    parser.add_argument("--features_dir", default="../features_output",
                        help="多设备特征目录")
    parser.add_argument("--prediction_windows", type=int, nargs="+",
                        default=DEFAULT_PREDICTION_WINDOWS,
                        help=f"预测窗口列表 (分钟), 默认 {DEFAULT_PREDICTION_WINDOWS}; "
                             f"每个窗口训练并保存独立模型")
    parser.add_argument("--model_dir", default="models",
                        help="模型输出根目录;实际模型保存到 {model_dir}/.../{window}min/")
    parser.add_argument("--combine", action="store_true",
                        help="合并所有设备训练统一模型")
    args = parser.parse_args()

    device_info = get_device_info()
    log.info(f"已知设备: {len(device_info)} 台")
    log.info(f"预测窗口序列: {args.prediction_windows} min "
             f"(purge={PURGE_WINDOW_MIN}min, embargo={EMBARGO_MIN}min)")

    # 汇总表: { window_min: { device_or_'combined': {auc, f1, ...} } }
    summary: dict = {}

    for window in args.prediction_windows:
        log.info(f"\n{'#'*60}\n# 预测窗口: {window} 分钟\n{'#'*60}")
        summary[window] = {}

        if args.all_devices:
            features_dir = args.features_dir
            if args.combine:
                model_dir = os.path.join(args.model_dir, "combined", f"{window}min")
                res = process_combined(device_info, features_dir, window, model_dir)
                if res:
                    summary[window]["combined"] = _summary_metrics(res, _pick_best(res))
            else:
                for code, info in device_info.items():
                    fpath = os.path.join(features_dir, f"features_{code}.parquet")
                    if not os.path.exists(fpath):
                        continue
                    model_dir = os.path.join(args.model_dir, code, f"{window}min")
                    res = process_device(code, info["numeric_id"], info["name"],
                                         fpath, window, model_dir)
                    if res:
                        summary[window][code] = _summary_metrics(res, _pick_best(res))
        elif args.device_code:
            info = device_info.get(args.device_code)
            if not info:
                log.error(f"未找到设备: {args.device_code}")
                log.info(f"可用: {list(device_info.keys())}")
                return
            features_path = args.features or \
                os.path.join(args.features_dir, f"features_{args.device_code}.parquet")
            model_dir = os.path.join(args.model_dir, f"{window}min")
            res = process_device(args.device_code, info["numeric_id"], info["name"],
                                 features_path, window, model_dir)
            if res:
                summary[window][args.device_code] = _summary_metrics(res, _pick_best(res))
        else:
            print(f"已知设备 ({len(device_info)} 台):")
            for code, info in device_info.items():
                print(f"  {code}  ({info['name']})")
            print(f"\n用法:")
            print(f"  python train_fault_predictor.py --device_code 102000000996 --features ../features_output/features_102000000996.parquet")
            print(f"  python train_fault_predictor.py --all_devices --combine --features_dir ../features_output/")
            print(f"  python train_fault_predictor.py --all_devices --combine --prediction_windows 60 120 240")
            return

    if summary and any(summary.values()):
        log.info(f"\n{'='*70}\n多窗口汇总 (best model AUC / Precision / Recall)\n{'='*70}")
        for window, by_target in summary.items():
            for tgt, m in by_target.items():
                log.info(f"  window={window:>3}min  {tgt:<14} {m['model']:<14} "
                         f"AUC={m['auc_roc']:.3f}  P={m['precision']:.3f}  R={m['recall']:.3f}")


def _pick_best(res: dict) -> str:
    """与 train_evaluate 保存逻辑一致:按 AUC 选最佳模型"""
    xgb_auc = res.get("xgboost", {}).get("auc_roc", -1)
    rf_auc = res.get("random_forest", {}).get("auc_roc", -1)
    return "xgboost" if xgb_auc >= rf_auc else "random_forest"


def _summary_metrics(res: dict, model_key: str) -> dict:
    m = res.get(model_key, {})
    return {
        "model": model_key,
        "auc_roc": m.get("auc_roc", 0.0),
        "precision": m.get("precision", 0.0),
        "recall": m.get("recall", 0.0),
        "f1": m.get("f1", 0.0),
    }


if __name__ == "__main__":
    main()
