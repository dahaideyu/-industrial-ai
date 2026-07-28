# 设备参数分析 / 特征视图 —— 现状审计与加强清单

> 审计日期：2026-06-05
> 范围：`/device-params` 页面相关的「参数分析」与「特征视图」两块
> 关联设计文档：[device-params.md](./device-params.md)

## 一、涉及的关键文件

| 文件 | 角色 |
|------|------|
| `backend/modules/device_param/services.py` | TimescaleDB 数据查询（原始 / 压缩 / 运行时段 / 告警） |
| `backend/modules/device_param/routes.py` | API 路由（`/data` `/analyze` `/features` `/anomaly/detect` `/aligned-data` 等） |
| `backend/modules/device_param/analysis_service.py` | LLM 参数分析 |
| `backend/tools/extract_device_features.py` | 离线特征工程（滑窗 / 交互 / 告警特征） |
| `frontend/src/views/DeviceParams.vue` | 页面：参数视图 + 特征视图 + 异常检测 |

数据源现状：原始/绘图数据走**实时表 `device_alarm_info`**（旧表 `dev_device_param_detail_record` 已于 **2026-04-21 02:00 停采**）。

---

## 二、审计发现（按优先级）

### 🔴 P0-1 数据源不一致 —— 已修复 ✅

- **问题**：`get_param_data()`（绘图/异常检测）已切到实时表 `device_alarm_info`，但
  `get_compressed_param_data()`（**AI 分析 `/analyze` 用**）仍在查停采的旧表
  `dev_device_param_detail_record`。
- **后果**：`POST /analyze` 喂给 LLM 的压缩数据拿不到 2026-04-21 之后的任何数据，
  绘图正常、AI 分析却基于过期/空数据，问题隐蔽。
- **修复**（`services.py` `get_compressed_param_data`）：
  - 数据源 `dev_device_param_detail_record` → `device_alarm_info`
  - 字段映射 `device_code→device_id`、`p_name→point_id`、`gather_time→point_time`
  - 取值逻辑对齐 `get_param_data`：`LEFT JOIN LATERAL` 从
    `raw_json->devices[]->points[]->point_value` 取全精度字符串，回退 `point_value` 列
  - 运行时段 OR 条件、整体时间范围条件的列名同步改为 `a.point_time`
  - 更新 docstring 说明数据源切换原因

### 🔴 P0-2 特征逻辑双份实现（待办）

- 后端 `extract_device_features.py`（Python）算一套特征；
  前端 `DeviceParams.vue`（约 `:612` 起）用 JS **又现算一套**（5min 重采样 + 滑动统计 + 变化率），
  仅靠注释「与后端语义一致」手动对齐。
- 前端特征视图**未调用** `/features` 接口，两边一旦改动即 drift。
- **建议**：前端特征视图改为消费后端 `/features`，或后端统一为唯一特征计算入口。

### 🟠 P1-1 多粒度聚合方案未落地

- `device-params.md` 设计的「B+D 自动降采样」未实现：`/data`（`routes.py`）仍是
  原始数据一次性返回，`limit` 默认 **300000 / 上限 500000**，无 `time_bucket` 聚合、无分页。
- 大时间跨度会同时拉爆后端查询与前端 ECharts 渲染。
- **建议**：`/data` 增加 `interval` 参数（auto/5min/15min/1hour/4hour/1day），
  利用 TimescaleDB `time_bucket()`；默认 limit 调小。

### 🔴 P1-2 预测能力未打通 —— 经核查为系统性阻塞（需数据科学返工）

- 设计文档第三节的 `predict_service.py`（故障预测 + 剩余寿命）尚未建立。
- 目前页面仅有 `/anomaly/detect`（IQR + 孤立森林），缺故障预测与剩余寿命。
- **核查结论（2026-06-05，实测）**：ML 故障预测管线整体**绑死在停采的旧表**，
  现阶段无法对实时数据出有效预测：

  | 证据 | 数据 |
  |---|---|
  | 模型基础点位（`models/102000000996/fault_predictor_best.pkl`，986 特征/AUC 0.984） | 66 个 |
  | 与**旧表** `dev_device_param_detail_record` 重叠 | 55/55（全中）→ 模型按旧表 schema 训练 |
  | 与**新表** `device_alarm_info` 重叠 | 仅 11/66（~17%） |
  | 特征管线 `extract_device_features.fetch_one_day`（line 167） | 查旧表 → 近 7 天 `_build_features_on_the_fly` 返回 **0 行** |
  | 新表点位构成 | 大量为 `AlarmMix1..27`（告警位），缺模型所需工艺点 |

- **双重断裂**：
  1. 特征管线读死表 → 近期数据抽不出特征（`/features` 实时路径对新日期返回空，回退过期 parquet）。
  2. 模型按旧 schema 训练 → 即便管线改指新表，83% 模型特征在新表缺失，
     `_align_features` 全填 0 → 预测必然失真。
- **落地前置条件**（数据科学任务，非纯集成）：
  1. ✅ **已完成**：`extract_device_features.fetch_one_day` 改为 **UNION 新旧两表**
     （旧表覆盖历史、新表 `device_alarm_info` 覆盖停采后，LATERAL 取全精度值），
     自适应跨越 4-21 边界。实测：近 3 天 0 行 → **1058 行/380 列**；历史 4/15-18
     仍 729 行/986 列（旧表富 schema 未破坏）。详见
     [prediction-rework 方案](./device-params-prediction-rework.md)。
  2. ⬜ 在 `device_alarm_info` 新 schema 上**重新训练**故障预测模型
     （新表仅 ~380 列、点位以 `AlarmMix*` 为主，与旧模型 986 特征差异大）。
  3. ⬜ 之后再建 `predict_service.py` + `POST /predict`，复用现成的
     `maintenance_report.services.fault_predictor.FaultPredictor`（已支持 `.pkl` 加载 / SHAP 解释）。

> 关联：这也解释了 P0-2 —— 前端特征视图之所以自己用 JS 现算（而非调 `/features`），
> 客观上成了**当前唯一能在实时数据上工作的特征路径**；后端管线对实时数据已失效。

### 🟡 P2-1 `/features` 接口路径分叉

- `routes.py` 中 ≤7 天实时计算、>7 天读 parquet；parquet 不存在直接 500，无降级。

### 🟡 P2-2 工程细节

- `services.py` 每请求 `new TimescaleDB()` + connect/close，**无连接池**。
- `services.py` 数据库密码存在**硬编码 fallback**（应仅走环境变量）。
- 前端特征在主线程现算，大数据量卡 UI，无 Web Worker / 增量计算。

---

## 三、加强清单（落地顺序）

| 优先级 | 事项 | 改动点 | 状态 |
|---|---|---|---|
| 🔴 P0 | 修数据源 Bug：`get_compressed_param_data` 切 `device_alarm_info` | `services.py` | ✅ 完成 + 实测通过 |
| 🔴 P0 | 统一特征计算：前端特征视图改用 `/features`（或后端唯一入口） | `routes.py` + `DeviceParams.vue` | ⬜ 待办 |
| 🟠 P1 | `/data` 加 `interval` 聚合（默认 raw 零破坏） | `services.py` + `routes.py` | ✅ 后端完成 + 实测通过 |
| 🟠 P1 | 前端大跨度自动降采样（参数视图 >48h 用 auto） | `DeviceParams.vue` | ✅ 完成 + 构建通过 |
| 🔴 P1 | 故障预测落地：①特征管线重指新表 | `extract_device_features.py` | ✅ 完成 + 实测通过 |
| 🔴 P1 | 故障预测落地：②模型重训 ③建 predict_service | 重训 + 新建 `predict_service.py` | ⛔ 阻塞（需数据科学返工，见方案文档） |
| 🟡 P2 | 连接池 + 移除硬编码密码 | `services.py` | ⬜ 待办 |
| 🟡 P2 | 特征前端计算移至 Web Worker / 增量 | `DeviceParams.vue` | ⬜ 待办 |

---

## 五、本轮已落地的代码改动

### P0-1 数据源修复（`services.py` `get_compressed_param_data`）
见 [上文 P0-1](#-p0-1-数据源不一致--已修复-)。

### P1-1 多粒度聚合（`services.py` + `routes.py`）
- **新增** `TimescaleDB.get_param_data_aggregated()`：基于 `device_alarm_info` +
  `time_bucket()` 按粒度聚合，返回每点 `value(avg)/min/max/std/count`。
- **新增** `TimescaleDB.resolve_interval()`：按时间跨度自动选档
  （≤6h→5min，≤24h→15min，≤72h→1hour，≤168h→4hour，>168h→1day）。
- **`/data` 路由** 新增 `interval` 查询参数：
  - `interval=raw`（**默认**）→ 行为与原来完全一致，**零破坏**。
  - `interval=auto` 或具体档位 → 走聚合分支，返回中带 `aggregated=true` 和实际 `interval`。
### P1-1 前端接入（`DeviceParams.vue`）
- `loadData()` 计算时间跨度：**仅参数视图且跨度 >48h** 时传 `interval=auto`，
  其余（含特征视图、≤48h）保持 `raw`，**行为零破坏**。
  - 特征视图必须保持 raw：前端要用原始点现算特征，喂聚合 avg 会破坏特征语义。
- 顶部新增「已按 {粒度} 聚合」提示徽标（`aggInterval` 状态，从响应 `aggregated`/`interval` 取）。
- 图表读 `value`（聚合时为 avg），格式与原始点兼容，无需改渲染逻辑。

> 附带：拉取带进的 SQL-QA 代码 import `marked`（`^18.0.4` 已在 package.json），
> 但旧 `node_modules` 未装导致 `npm run build` 失败。已 `npm install` 修复，构建恢复绿色。

---

## 六、验证结果（2026-06-05，已通过 DB 隧道实测）

验证脚本：`backend/tools/_probe_compressed_fix.py`（直连真实库，比对压缩查询与原始查询逐参数计数）。
测试设备 `102000000996`，最近 24h（约 10.4 万行 / 16 参数）。

### P0-1 数据源修复 ✅
- 确认 `get_compressed_param_data` 已从 `device_alarm_info` 取数（旧表已停采）。
- 16 个参数计数与 `get_param_data`（绘图路径）**逐一完全一致**，`[result] ✅`。

### 验证中发现并修复的附带 Bug：负值被丢弃
- 初次比对时 `Tec_lead_Real_weight` 差 32 条 → 定位为该参数有 32 个 `-1`。
- 根因：SQL 数值正则 `^[0-9]+(\.[0-9]*)?$` **不认负号**，而绘图路径用 Python `float()` 认，
  导致 AI 分析与绘图看到的数据不一致（负值在聚合里被静默丢弃）。
- 修复：两处 cast 正则改为 `^-?[0-9]+(\.[0-9]*)?$`（`get_compressed_param_data` +
  `get_param_data_aggregated`）。修复后 16 参数计数全部一致。

### P1-1 多粒度聚合 ✅
- `time_bucket()` 在 `device_alarm_info` 上可用，聚合正常。
- 档位自动选择实测：3/6h→5min，12/24h→15min，48/72h→1hour，120/168h→4hour，>168h→1day。
- 24h 跨度 `auto`→15min（97 点/参数），`1hour`→25 点/参数；每点含 value/min/max/std/count。

---

## 四、P0-1 修复验证建议

修复后建议对 `/analyze` 做一次回归：

1. 选一台有近期（2026-04-21 之后）数据的设备。
2. 时间范围选最近 24h，分别测 `analyze_running_only=true / false`。
3. 确认返回的 `compressed_data.series` 非空、`total_hours` 合理、`avg/min/max` 有值。
4. 与 `/data` 同设备同时段的原始数据对比，确认数量级一致（避免 LATERAL 取值漏点）。
