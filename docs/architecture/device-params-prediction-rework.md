# 设备故障预测 —— 返工实施方案

> 编写：2026-06-05
> 关联：[device-params-audit.md](./device-params-audit.md)（审计与发现）、
> [device-params.md](./device-params.md)（原始设计）
> 状态：阶段一已完成并实测；阶段二/三待数据科学返工

## 一、背景与根因

2026-04-21 02:00 设备点位采集从旧表 `dev_device_param_detail_record` 切换到
实时表 `device_alarm_info`。但**特征工程与 ML 故障预测整条链路仍绑死在旧表/旧 schema**，
导致对实时数据完全失效。实测证据（设备 `102000000996`）：

| 维度 | 旧表 `dev_device_param_detail_record` | 新表 `device_alarm_info` |
|---|---|---|
| 采集状态 | 已于 2026-04-21 停采 | 实时，更新至今 |
| 点位数（该设备） | 55 | 48（大量为 `AlarmMix1..27` 告警位） |
| 与模型 66 个基础点位重叠 | 55（全中） | 11（~17%） |
| 特征管线产出（近 7 天） | —— | 修复前 **0 行** |

**双重断裂**：
1. **数据源断裂**：`extract_device_features.fetch_one_day` 查旧表 → 近期无数据。
2. **Schema 断裂**：现有 `.pkl` 模型（986 特征，AUC 0.984）按旧表点位训练，
   新表仅 ~17% 特征存在，`FaultPredictor._align_features` 会把缺失列全填 0 → 预测失真。

---

## 二、阶段一：特征管线重指新表 ✅ 已完成

**改动**：`backend/tools/extract_device_features.py` 的 `fetch_one_day()`。

将单表查询改为 **UNION 新旧两表**，自适应跨越 4-21 边界：
- 旧表覆盖历史（≤ 4-21）；新表 `device_alarm_info` 覆盖停采后至今。
- 新表全精度值经 `LEFT JOIN LATERAL` 从 `raw_json->devices[]->points[]->point_value`
  按 `point_id` 取出，回退 `point_value` 列（与 `services.get_param_data` 一致）。
- `device_code` 在两表为同一业务编码（`device_alarm_info.device_id`）。
- 某一天通常仅一张表有数据，UNION 成本≈有数据的那张表。

**实测验证**（`_build_features_on_the_fly`，设备 102000000996）：

| 区间 | 修复前 | 修复后 |
|---|---|---|
| 近 3 天（新表期） | 0 行 | **1058 行 / 380 列**，覆盖至 2026-06-05 |
| 历史 4/15–4/18（旧表期） | 729 行 / 986 列 | **729 行 / 986 列（未破坏）** |

**收益**：`/features` 实时路径、parquet 预生成、训练数据抽取现在都能跨越 4-21
边界拿到连续数据，是阶段二/三的前提。

> 注意：新旧 schema 列数不同（986 vs 380）。跨边界时间范围会得到两套列的并集 +
> 大量 NaN，重训时需明确训练区间与特征集（见阶段二）。

---

## 三、阶段二：在新 schema 上重新训练模型 ⬜ 待办（数据科学）

现有模型不可直接用于实时数据，必须基于 `device_alarm_info` 重训。

### 3.1 关键决策点
1. **特征集对齐**：新表仅 ~380 列且以告警位为主，缺旧表大量工艺点。需确认：
   - 新表是否真的不再采集那些工艺点（确认数据采集侧，而非仅本设备样本）。
   - 若工艺点确实消失，故障预测的可用信号大幅减少，需重新评估可行性与目标指标。
2. **训练区间**：建议仅用新表期（> 2026-04-21）数据训练，避免跨 schema 拼接的 NaN 污染。
   需积累足够时长 + 足够故障样本。
3. **标签来源**：原模型正样本极少（102000000996：1635 样本仅 16 个故障，recall 仅 0.44）。
   需明确故障标签定义（来自 `dev_device_status_record` 告警状态？维修工单？），
   并评估样本是否支撑监督学习；样本太少应考虑无监督/半监督（已有 `/anomaly/detect`）。

### 3.2 训练产物约定（沿用现有 `FaultPredictor` 加载格式）
`.pkl` 须为 dict：`{model, model_type, feature_names, metrics}`，
落到 `backend/models/{device_code}/fault_predictor_best.pkl`，
并产出 `evaluation_report.json`。这样阶段三可直接复用现成加载器。

### 3.3 评估
- 不能只看 AUC（旧模型 AUC 0.984 但 recall 0.44，漏报严重）。
- 关注 recall / PR-AUC / 故障提前量；按设备分别评估（不同设备 schema/工况不同）。

---

## 四、阶段三：构建预测服务并接入页面 ⬜ 待办（重训后）

### 4.1 后端 `predict_service.py`（新建于 `modules/device_param/`）
- 复用 `_build_features_on_the_fly(device_code, st, et)` 取实时特征。
- 复用 `maintenance_report.services.fault_predictor.FaultPredictor`
  （已支持 `.pkl` 加载、`predict`/`predict_latest`、`_align_features`、SHAP 解释）。
- 模型路径按设备：`models/{device_code}/fault_predictor_best.pkl`，回退 combined。
- 输出：故障概率时间线 + 最新风险等级 + Top 贡献特征（SHAP）+（可选）LLM 解读
  （`build_fault_explanation_prompt` 已现成）。

### 4.2 后端路由
`POST /api/device-params/predict`（参考 audit 文档 3.2.2），返回 `predict_service` 结果。

### 4.3 前端 `DeviceParams.vue`
增加「预测」按钮 + 结果面板（健康/故障概率/Top 特征/剩余寿命）。
参考 [device-params.md](./device-params.md) §3.2.3 的面板草图。

### 4.4 剩余寿命
旧 `device_warning/ai_analysis/fault_predictor.py` 有 `estimate_remaining_life`
（规则/外推法），可作为补充；但同样依赖工艺点，受 schema 变化影响，需重新校核阈值。

---

## 五、风险与依赖

| 风险 | 说明 | 缓解 |
|---|---|---|
| 新表工艺点缺失 | 若关键工艺点不再采集，监督式故障预测可能不可行 | 先确认采集侧；不行则转无监督异常检测 |
| 故障样本稀少 | 监督学习正样本不足，模型漏报 | 明确标签来源；考虑半监督/异常检测 |
| 按设备 schema 不一 | 不同设备点位不同，需分设备训练/评估 | 模型按 `device_code` 隔离存放（已是现状） |
| 跨边界 NaN | 训练区间跨 4-21 引入大量缺失列 | 仅用新表期训练 |

---

## 六、两套 fault_predictor 辨析（避免误用）

| 文件 | 类型 | 用途 |
|---|---|---|
| `modules/maintenance_report/services/fault_predictor.py` | **ML（XGBoost），加载 `.pkl` + SHAP** | 阶段三复用此处 |
| `modules/device_warning/ai_analysis/fault_predictor.py` | 规则/统计（`predict_faults`/`estimate_remaining_life`） | 剩余寿命可参考 |
| `modules/device_param/anomaly_detector.py` | IQR + 孤立森林（无监督） | 已接入 `/anomaly/detect`，故障样本不足时的兜底 |
