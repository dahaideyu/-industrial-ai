# 设备参数监控页面分析与预测方案

## 一、页面现状分析

### 1.1 页面功能概述

`/device-params` 页面（`frontend/src/views/DeviceParams.vue`）是设备参数监控与 AI 分析页面，核心功能：

| 功能 | 说明 |
|------|------|
| 设备选择 | 下拉列表获取所有设备（`GET /api/device-params/devices`） |
| 时间范围 | 手动选择开始/结束时间，默认当天 00:00 ~ 当前时刻 |
| 参数曲线 | ECharts 多系列折线图，每个参数独立 Y 轴，支持显示/隐藏切换 |
| 运行时段 | 顶部绿色条显示设备运行时段（`GET /api/device-params/running-periods`） |
| AI 分析 | 将压缩数据发给 LLM 做趋势/异常/关联/健康/维护分析（`POST /api/device-params/analyze`） |

### 1.2 数据流

```
TimescaleDB (10.1.2.227:5432)
    └─ dev_device_param_detail_record  (时间序列原始数据)
    └─ dev_device_status_record        (运行时段)
    └─ device_info                     (设备列表)
    └─ dev_device_param                (参数定义)
         │
         ▼
   services.py (TimescaleDB 类)
    ├─ get_param_data()           → 原始时间序列 (limit=5000, max=20000)
    ├─ get_compressed_param_data() → 按小时聚合 (avg/min/max/std/count)
    └─ get_running_periods()      → 运行时段列表
         │
         ▼
   routes.py (FastAPI)
    ├─ GET  /data             → 原始数据（前端绘图用）
    ├─ GET  /running-periods  → 运行时段
    └─ POST /analyze          → 压缩数据 + LLM 分析
         │
         ▼
   DeviceParams.vue
    └─ ECharts 图表 + AI 分析结果展示
```

### 1.3 当前数据量问题

**核心矛盾**：设备参数采集频率高（约每 5 分钟一条），一个设备可能有多达 15+ 个参数点位。

| 时间跨度 | 单参数数据点 | 15 个参数总点数 | 数据量评估 |
|---------|------------|--------------|----------|
| 1 天 | ~288 条 | ~4,320 条 | 可接受 |
| 3 天 | ~864 条 | ~12,960 条 | 接近 limit 上限 |
| 7 天 | ~2,016 条 | ~30,240 条 | **超出 20000 上限** |
| 30 天 | ~8,640 条 | ~129,600 条 | 严重超限 |

**当前限制**：
- `GET /data` 接口硬限制 `limit` 最大 20000，无分页 offset
- 前端一次性加载全部数据，无懒加载/虚拟滚动
- ECharts 一次性渲染所有数据，数据量过大会卡顿
- AI 分析的 `get_compressed_param_data()` 限制 max_hours=72、max_points_per_series=288

---

## 二、多天数据加载方案

### 2.1 方案对比

| 方案 | 适用场景 | 复杂度 | 优点 | 缺点 |
|------|---------|-------|------|------|
| **A. 服务端分页** | 需要浏览全部原始数据 | 中 | 不丢数据 | 多次请求、拼接复杂 |
| **B. 多粒度聚合** | 趋势看大局、细节看局部 | 中 | 性能好、体验好 | 需要切换粒度 |
| **C. 时间窗口滑动** | 实时监控场景 | 低 | 实现简单 | 无法总览全局 |
| **D. 数据降采样** | 大时间跨度绘图 | 低 | 一请求搞定 | 丢失细节 |

### 2.2 推荐方案：B + D 组合（多粒度聚合 + 自动降采样）

**核心思路**：根据用户选择的时间范围，自动选择合适的数据粒度，一次请求返回适异数据量。

```
时间范围              聚合粒度       最大数据点
─────────────────────────────────────────────
≤ 6 小时              原始(5min)      ~72/参数
6h ~ 24h              15分钟聚合      ~96/参数
24h ~ 72h             1小时聚合       ~72/参数
3天 ~ 7天              4小时聚合       ~42/参数
7天 ~ 30天             1天聚合         ~30/参数
> 30天                 1周聚合         ~4/参数/周
```

**实现要点**：

1. **后端新增聚合查询接口**（或在现有 `/data` 接口增加 `interval` 参数）：

```python
# services.py 新增方法
def get_param_data_aggregated(
    self,
    device_code: str,
    start_time: datetime,
    end_time: datetime,
    interval: str = "auto",  # auto / 5min / 15min / 1hour / 4hour / 1day
) -> Dict:
    """根据时间范围自动选择粒度，返回聚合数据"""

    hours = (end_time - start_time).total_seconds() / 3600

    # 自动选择粒度
    if interval == "auto":
        if hours <= 6:
            interval = "5min"
        elif hours <= 24:
            interval = "15min"
        elif hours <= 72:
            interval = "1hour"
        elif hours <= 168:
            interval = "4hour"
        else:
            interval = "1day"

    # SQL 聚合查询（利用 TimescaleDB 的 time_bucket 函数）
    interval_map = {
        "5min":  "INTERVAL '5 minutes'",
        "15min": "INTERVAL '15 minutes'",
        "1hour": "INTERVAL '1 hour'",
        "4hour": "INTERVAL '4 hours'",
        "1day":  "INTERVAL '1 day'",
    }

    pg_interval = interval_map[interval]

    query = f"""
        SELECT
            p_name,
            time_bucket({pg_interval}, gather_time) AS bucket,
            AVG(p_value_num) AS avg_val,
            MIN(p_value_num) AS min_val,
            MAX(p_value_num) AS max_val,
            STDDEV(p_value_num) AS std_val,
            COUNT(*) AS cnt
        FROM (
            SELECT p_name, gather_time,
                CASE WHEN p_value ~ '^[0-9]+(\\.[0-9]*)?$'
                     THEN p_value::double precision ELSE NULL END AS p_value_num
            FROM dev_device_param_detail_record
            WHERE device_code = %s
              AND gather_time >= %s AND gather_time <= %s
        ) sub
        WHERE p_value_num IS NOT NULL
        GROUP BY p_name, bucket
        ORDER BY p_name, bucket
    """
```

2. **前端改造**：

```javascript
// 查询时不需要改逻辑，后端自动适配
// 可增加粒度切换 UI 让用户手动选择
const interval = ref('auto')

async function loadData() {
  const res = await getDeviceParamData({
    device_code: selectedDevice.value,
    start_time: formatForApi(startTime.value),
    end_time: formatForApi(endTime.value),
    interval: interval.value,  // 新增参数
  })
}
```

3. **数据格式兼容**：聚合数据返回格式与原始数据兼容，前端 ECharts 可直接使用，只需额外显示 min/max 区间：

```python
# 返回格式兼容
{
  "series": {
    "Tec_Bd_Yc": [
      {
        "time": "2025-05-14 10:00:00",
        "value": 52.3,       # avg
        "min": 48.1,         # 新增
        "max": 55.2,         # 新增
        "std": 1.8,          # 新增
        "count": 12          # 新增
      }
    ]
  }
}
```

4. **ECharts 增强显示**：在聚合模式下，用面积图展示 min/max 区间：

```javascript
// 当数据有 min/max 时，添加 areaStyle 展示波动范围
seriesList.push({
  name: displayName,
  type: 'line',
  data: values.map((v, i) => [time, v]),
  // min/max 区间带
  markArea: { /* ... */ },
  // 或使用 arearange 系列类型
})
```

---

## 三、设备信息预测方案

### 3.1 现有预测能力

项目中已有两套预测体系，但分布在 `device_warning` 模块，与 `device_param` 页面**未打通**：

| 模块 | 文件 | 能力 | 当前状态 |
|------|------|------|---------|
| 异常检测 | `anomaly_detector.py` | 阈值越限/突变/漂移/卡死检测 + 报警预测 | 在 device_warning 中，页面未集成 |
| 故障预测 | `fault_predictor.py` | 6类故障模式识别 + 剩余寿命估算 | 在 device_warning 中，页面未集成 |
| AI 分析 | `analysis_service.py` | LLM 趋势/异常/关联分析 | 已在页面集成 |

### 3.2 预测方案设计

#### 方案架构

```
                          ┌─────────────────────────┐
                          │   DeviceParams.vue       │
                          │  ┌───────────────────┐  │
                          │  │  新增"预测"按钮    │  │
                          │  └────────┬──────────┘  │
                          └───────────┼─────────────┘
                                      │
                              POST /api/device-params/predict
                                      │
                          ┌───────────┼─────────────┐
                          │           ▼              │
                          │   predict_service.py     │
                          │  ┌───────────────────┐  │
                          │  │ 1. 加载历史数据     │  │
                          │  │ 2. 调用异常检测     │  │
                          │  │ 3. 调用故障预测     │  │
                          │  │ 4. 剩余寿命估算     │  │
                          │  │ 5. LLM 综合解读    │  │
                          │  └───────────────────┘  │
                          │           │              │
                          │     ┌─────┴─────┐       │
                          │     ▼           ▼       │
                          │  anomaly_    fault_     │
                          │  detector   predictor   │
                          └─────────────────────────┘
```

#### 3.2.1 后端：新建预测服务

**新增文件**：`backend/modules/device_param/predict_service.py`

```python
"""
设备参数预测服务
整合 anomaly_detector 和 fault_predictor，为 device_param 页面提供预测能力
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

import pandas as pd
import numpy as np

from ..device_warning.ai_analysis.anomaly_detector import (
    AnomalyDetector, AnomalyType
)
from ..device_warning.ai_analysis.fault_predictor import (
    FaultPredictor, FaultType
)
from ..device_warning.ai_analysis.point_config import (
    PROCESS_POINT_DISPLAY_NAMES, PROCESS_POINT_THRESHOLDS
)
from .services import TimescaleDB


@dataclass
class PredictionResult:
    """预测结果"""
    anomalies: List[Dict]          # 检测到的异常
    alarm_predictions: List[Dict]  # 报警预测
    fault_predictions: List[Dict]  # 故障预测
    remaining_life: Dict           # 剩余寿命估算
    health_score: float            # 健康评分 (0-100)
    summary: str                   # LLM 综合解读


async def predict_device_params(
    device_code: str,
    device_name: str,
    start_time: datetime,
    end_time: datetime,
) -> PredictionResult:
    """
    对设备参数进行预测分析

    步骤：
    1. 从 TimescaleDB 加载历史数据
    2. 转换为 anomaly_detector / fault_predictor 需要的 DataFrame 格式
    3. 执行异常检测
    4. 执行故障预测
    5. 估算关键部件剩余寿命
    6. 计算健康评分
    7. （可选）LLM 综合解读
    """
    db = TimescaleDB()
    if not db.connect():
        raise ConnectionError("TimescaleDB 连接失败")

    try:
        # 1. 加载数据 — 需要足够的历史数据做基线
        rows = db.get_param_data(
            device_code=device_code,
            start_time=start_time,
            end_time=end_time,
            limit=20000,
        )

        if not rows:
            return PredictionResult(
                anomalies=[], alarm_predictions=[],
                fault_predictions=[], remaining_life={},
                health_score=100, summary="无数据，无法预测"
            )

        # 2. 转换为 DataFrame 格式
        #    anomaly_detector 期望: {参数名: DataFrame(采集时间, 参数值)}
        history_data = {}
        name_map = db.get_point_names(device_code)

        for row in rows:
            pname = name_map.get(row["p_name"], row["p_name"])
            if pname not in history_data:
                history_data[pname] = {
                    "采集时间": [],
                    "参数值": [],
                }
            if row["p_value_num"] is not None and row["gather_time"]:
                history_data[pname]["采集时间"].append(row["gather_time"])
                history_data[pname]["参数值"].append(row["p_value_num"])

        history_dfs = {}
        for pname, data in history_data.items():
            df = pd.DataFrame(data)
            if len(df) >= 5:
                history_dfs[pname] = df

        # 3. 异常检测
        config = {
            "parameter_thresholds": PROCESS_POINT_THRESHOLDS.get(device_code, {}),
        }
        detector = AnomalyDetector(config=config)
        detector.calculate_baselines(history_dfs)
        anomalies = detector.detect_anomalies(history_dfs)
        alarm_preds = detector.predict_alarms(history_dfs)

        # 4. 故障预测
        predictor = FaultPredictor(config=config)
        fault_preds = predictor.predict_faults(history_dfs)

        # 5. 剩余寿命
        remaining_life = {}
        features = predictor.baselines
        for param_name, threshold_val in [("布袋压差", 80), ("过滤器压差", 100)]:
            rl = predictor.estimate_remaining_life(param_name, features, threshold_val)
            if rl is not None:
                remaining_life[param_name] = str(rl)

        # 6. 健康评分
        health_score = _calculate_health_score(anomalies, alarm_preds, fault_preds)

        # 7. 序列化结果
        result = PredictionResult(
            anomalies=[_serialize_anomaly(a) for a in anomalies[:50]],  # 限制数量
            alarm_predictions=[_serialize_alarm_pred(p) for p in alarm_preds],
            fault_predictions=[_serialize_fault_pred(p) for p in fault_preds],
            remaining_life=remaining_life,
            health_score=health_score,
            summary="",  # 可选：调用 LLM 生成综合解读
        )

        return result

    finally:
        db.close()


def _calculate_health_score(anomalies, alarm_preds, fault_preds) -> float:
    """根据异常/预测数量计算健康评分"""
    score = 100.0

    # 异常扣分
    severity_weights = {"严重": 15, "高": 8, "中": 3, "低": 1}
    for a in anomalies:
        score -= severity_weights.get(a.severity, 1)

    # 报警预测扣分
    for p in alarm_preds:
        score -= p.probability * 10

    # 故障预测扣分
    for p in fault_preds:
        score -= p.probability * 15

    return max(0, min(100, round(score, 1)))


def _serialize_anomaly(a):
    return {
        "timestamp": a.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "parameter": a.parameter,
        "value": round(a.value, 2),
        "type": a.anomaly_type.value,
        "severity": a.severity,
        "description": a.description,
    }


def _serialize_alarm_pred(p):
    return {
        "predicted_alarm": p.predicted_alarm,
        "probability": round(p.probability, 2),
        "estimated_time": str(p.estimated_time_to_alarm),
        "contributing_factors": p.contributing_factors,
        "recommendation": p.recommendation,
    }


def _serialize_fault_pred(p):
    return {
        "fault_name": p.fault_name or p.fault_type.value,
        "probability": round(p.probability, 2),
        "severity": p.severity,
        "estimated_occurrence": str(p.estimated_occurrence),
        "related_parameters": p.related_parameters,
        "warning_signs": p.warning_signs,
        "preventive_actions": p.preventive_actions,
        "confidence": round(p.confidence, 2),
    }
```

#### 3.2.2 后端：新增 API 端点

**修改文件**：`backend/modules/device_param/routes.py`

```python
@router.post("/predict")
async def predict_params(request: ParamAnalysisRequest):
    """对设备参数进行预测分析（异常检测 + 故障预测 + 剩余寿命）"""
    st, et = _parse_time_range(request)

    try:
        result = await predict_device_params(
            device_code=request.device_code,
            device_name=request.device_name or request.device_code,
            start_time=st,
            end_time=et,
        )
        return success_response(data=asdict(result))
    except Exception as e:
        return error_response(msg=f"预测分析失败: {str(e)}", code=500)
```

#### 3.2.3 前端：预测结果展示

在 `DeviceParams.vue` 中增加预测面板：

```
┌──────────────────────────────────────────────────┐
│  设备参数监控                                      │
│  [设备选择] [开始时间] [结束时间] [查询] [AI分析] [预测] │
├──────────────────────────────────────────────────┤
│                                                    │
│  ┌─ 参数趋势图 (ECharts) ──────────────────────┐  │
│  │  ...existing chart...                        │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  ┌─ 预测结果面板 ──────────────────────────────┐   │
│  │                                              │   │
│  │  健康评分:  78 / 100  ⚠️                     │   │
│  │  ████████░░░░░░░░░░░░░░░                     │   │
│  │                                              │   │
│  │  ⚡ 异常检测 (12 条)                          │   │
│  │  ┌──────┬──────┬──────┬──────┬──────┐       │   │
│  │  │ 时间  │ 参数  │ 类型  │ 严重度 │ 描述  │       │   │
│  │  ├──────┼──────┼──────┼──────┼──────┤       │   │
│  │  │ ...  │ ...  │ 越限  │ 高   │ ...  │       │   │
│  │  └──────┴──────┴──────┴──────┴──────┘       │   │
│  │                                              │   │
│  │  🔮 报警预测 (3 条)                           │   │
│  │  ┌──────┬──────┬──────┬──────┐              │   │
│  │  │报警名  │ 概率  │预计时间│ 建议  │              │   │
│  │  └──────┴──────┴──────┴──────┘              │   │
│  │                                              │   │
│  │  🔧 故障预测 (2 条)                           │   │
│  │  ┌──────┬──────┬──────┬──────┐              │   │
│  │  │故障名  │ 概率  │严重度  │措施   │              │   │
│  │  └──────┴──────┴──────┴──────┘              │   │
│  │                                              │   │
│  │  ⏳ 剩余寿命估算                               │   │
│  │  • 布袋压差: 预计 3天12小时 后需更换            │   │
│  │  • 过电器压差: 预计 7天2小时 后需更换           │   │
│  │                                              │   │
│  └──────────────────────────────────────────────┘   │
│                                                    │
│  ┌─ AI 分析结果 ──────────────────────────────┐   │
│  │  ...existing analysis...                    │   │
│  └──────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
```

---

## 四、数据量优化的具体实施步骤

### 4.1 第一阶段：后端聚合接口（解决"内容太多"问题）

1. **`services.py`** 新增 `get_param_data_aggregated()` 方法
   - 利用 TimescaleDB 的 `time_bucket()` 函数做时间粒度聚合
   - 自动根据时间范围选择粒度
   - 返回格式与原始数据兼容（avg 作为 value，附带 min/max/std）

2. **`routes.py`** 修改 `GET /data` 端点
   - 新增 `interval` 参数（默认 `auto`）
   - interval=auto 时自动选择粒度
   - interval=raw 时返回原始数据（保持向后兼容）

3. **前端 `client.js`** 新增 `interval` 参数

4. **前端 `DeviceParams.vue`**
   - 传递 `interval: 'auto'`
   - 可选：增加粒度切换 UI（原始/15分钟/1小时/4小时/1天）

### 4.2 第二阶段：预测功能集成

1. **新建 `predict_service.py`**，整合 anomaly_detector + fault_predictor
2. **`routes.py`** 新增 `POST /predict` 端点
3. **前端** 增加预测按钮 + 结果展示面板

### 4.3 第三阶段：前端交互优化（可选）

1. **数据点数提示**：查询前显示预计数据点数，超出时提醒切换粒度
2. **参数分组**：将参数按类型分组（温度/压力/物料/电气），减少同时显示数量
3. **图表虚拟化**：ECharts 大数据量时开启 `large: true` 和 `sampling: 'lttb'`
4. **流式加载**：长时间范围数据分片请求，前端逐步渲染

---

## 五、TimescaleDB 优化建议

### 5.1 确保 Hypertable 配置

```sql
-- 确认已是 hypertable
SELECT * FROM timescaledb_information.hypertables
WHERE hypertable_name = 'dev_device_param_detail_record';

-- 如未配置，转换
SELECT create_hypertable('dev_device_param_detail_record', 'gather_time',
  migrate_data => true, chunk_time_interval => INTERVAL '1 day');
```

### 5.2 创建聚合加速索引

```sql
-- 时间范围查询加速
CREATE INDEX IF NOT EXISTS idx_param_detail_device_gather
ON dev_device_param_detail_record (device_code, gather_time DESC);

-- 设备+参数+时间 复合索引
CREATE INDEX IF NOT EXISTS idx_param_detail_device_pname_gather
ON dev_device_param_detail_record (device_code, p_name, gather_time DESC);
```

### 5.3 创建连续聚合（Continuous Aggregate）

预计算常用粒度的聚合数据，查询时直接读预计算结果，无需实时聚合：

```sql
-- 1小时粒度聚合
CREATE MATERIALIZED VIEW device_param_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', gather_time) AS bucket,
    device_code,
    p_name,
    AVG(p_value::double precision) AS avg_val,
    MIN(p_value::double precision) AS min_val,
    MAX(p_value::double precision) AS max_val,
    STDDEV(p_value::double precision) AS std_val,
    COUNT(*) AS cnt
FROM dev_device_param_detail_record
WHERE p_value ~ '^[0-9]+(\.[0-9]*)?$'
GROUP BY bucket, device_code, p_name;

-- 自动刷新策略
SELECT add_continuous_aggregate_policy('device_param_hourly',
  start_offset => INTERVAL '3 hours',
  end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour');
```

### 5.4 数据保留策略

```sql
-- 原始数据保留 90 天，之后自动清理
SELECT add_retention_policy('dev_device_param_detail_record',
  INTERVAL '90 days');

-- 聚合数据保留更久
-- hourly 保留 1 年, daily 保留 3 年
```

---

## 六、关键文件清单

| 文件 | 角色 | 需修改/新建 |
|------|------|-----------|
| `backend/modules/device_param/services.py` | 数据查询 | 修改：新增聚合查询方法 |
| `backend/modules/device_param/routes.py` | API 路由 | 修改：新增 interval 参数 + predict 端点 |
| `backend/modules/device_param/predict_service.py` | 预测服务 | **新建**：整合异常检测+故障预测 |
| `frontend/src/views/DeviceParams.vue` | 页面组件 | 修改：增加预测面板+粒度选择 |
| `frontend/src/api/client.js` | API 客户端 | 修改：新增 predict 接口 + interval 参数 |
| `backend/modules/device_warning/ai_analysis/anomaly_detector.py` | 异常检测 | 不修改，被 predict_service 调用 |
| `backend/modules/device_warning/ai_analysis/fault_predictor.py` | 故障预测 | 不修改，被 predict_service 调用 |
| `backend/modules/device_warning/ai_analysis/point_config.py` | 参数配置 | 不修改，被 predict_service 引用 |
