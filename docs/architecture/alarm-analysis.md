# 报警分析系统架构

> 基于工业设备报警数据的实时分析系统，结合 SQL 统计聚合与 AI 异常检测，支持日报/周报/月报三种分析周期，覆盖报警查询、统计、AI 检测、预测与历史回溯。

---

## 一、系统架构

### 1.1 整体数据流

```
PostgreSQL / TimescaleDB（device_alarm_info 报警时序表）
    │
    ▼
PostgresDB（数据访问层）
    │  ├── 报警记录分页查询
    │  ├── 报警统计聚合（总量/按设备/按类型/按小时）
    │  └── 分析结果持久化（alarm_analysis_daily/weekly/monthly）
    │
    ├──────────────────────────────────────┐
    ▼                                      ▼
SQL 统计结果                          AI 分析引擎
(analyze_integrator)                (FactoryAIAnalyzer)
    │  ├── 总量 / 活跃数                │  ├── AnomalyDetector → 异常检测 & 报警预测
    │  ├── 按设备 Top10                 │  ├── HealthDashboard → 健康评分 & 风险评估
    │  ├── 按类型 Top10                 │  ├── FaultPredictor  → 故障预测 & 寿命评估
    │  └── 按小时趋势                   │  └── EnergyOptimizer → 能效分析 & 优化建议
    │                                      │
    ▼                                      ▼
        合并结果 → 保存到 PostgreSQL
                │
                ▼
        FastAPI Routes → Vue.js 前端
        (AlarmAnalysis.vue / Alarms.vue)
```

### 1.2 模块目录结构

```
backend/
├── routes/
│   └── alarms.py                     # 报警 API 主路由（/api/alarms*）
│
├── modules/device_warning/
│   ├── analysis_routes.py            # 设备分析 API（/api/device_analysis*）
│   ├── jobs_routes.py                # 任务管理 API（/api/jobs*）
│   ├── services/
│   │   ├── device_analyzer.py        # 分析服务编排层
│   │   └── job_manager.py            # 任务管理服务
│   └── ai_analysis/                  # AI 分析核心引擎
│       ├── main.py                   # FactoryAIAnalyzer 编排器
│       ├── postgres_loader.py        # 数据库连接池 & 全部 SQL 操作
│       ├── data_loader.py            # 数据加载（历史数据 + 报警事件）
│       ├── point_config.py           # 点位映射与设备配置中心
│       ├── anomaly_detector.py       # 异常检测引擎
│       ├── health_dashboard.py       # 健康评估引擎
│       ├── fault_predictor.py        # 故障预测引擎
│       ├── energy_optimizer.py       # 能效优化引擎
│       └── predictive_maintenance.py # 多设备编排器
```

---

## 二、报警数据源

### 2.1 核心数据表

| 表名 | 用途 |
|------|------|
| `device_alarm_info` | 报警时序数据（设备ID、点位ID、点位值、时间、设备状态） |
| `device_info` | 设备主数据（device_id → device_name） |
| `point_info` | 点位定义（point_id → point_name） |
| `alarm_analysis_daily` | 日报分析结果 |
| `alarm_analysis_weekly` | 周报分析结果 |
| `alarm_analysis_monthly` | 月报分析结果 |
| `analysis_job_run` | 任务执行记录 |
| `analysis_job_log` | 任务执行日志 |

### 2.2 数据特点

- `device_alarm_info` 表中 `point_value` 列含义因点位类型不同：
  - **报警点位**（Alarm_xxx）：值为 0/1（0=恢复，1=触发）
  - **工艺参数点位**（Tec_xxx）：值为实际数值（温度、功率、压力等）
- AI 分析模块主要处理工艺参数的连续数值，报警点位用于统计和触发判断
- 数据采样间隔约 5 分钟

### 2.3 点位映射体系

数据库存储技术点位 ID（如 `Tec_Power`、`Alarm1`），AI 模块使用中文逻辑名（如"主机功率"、"负风风压下限报警"）。`point_config.py` 提供所有映射：

| 映射配置 | 用途 |
|---------|------|
| `DEVICES` | 设备ID → 名称/类型 |
| `PROCESS_POINT_DISPLAY_NAMES` | point_id → 中文显示名 |
| `PROCESS_POINT_LOGIC_NAMES` | point_id → AI 模块参数名 |
| `ALARM_POINT_NAMES` | 报警 point_id → 报警中文名 |
| `PARAMETER_THRESHOLDS` | 每台设备的参数阈值（normal_low, normal_high, alarm_low, alarm_high） |
| `ALARM_PARAMETER_MAPPING` | 每台设备的报警→参数关联 |
| `FAULT_PATTERN_CONFIG` | 每台设备的故障模式定义 |

---

## 三、SQL 统计分析

### 3.1 报警记录查询（GET /api/alarms）

```
SELECT a.device_id, d.device_name, a.point_id, a.point_value,
       a.point_time, a.device_status, a.value_type
FROM device_alarm_info a
LEFT JOIN device_info d ON a.device_id = d.device_id
WHERE {conditions}
ORDER BY a.point_time DESC
LIMIT {page_size} OFFSET {offset}
```

支持过滤：device_id、时间范围、point_value=1（仅活跃）、point_id 模糊搜索。

### 3.2 报警统计聚合（GET /api/alarms/statistics）

四组聚合查询：

1. **总量统计**：总数 + 活跃数（`COUNT(*) FILTER (WHERE point_value = 1)`）
2. **按设备 Top10**：`GROUP BY device_id ORDER BY count DESC LIMIT 10`
3. **按类型 Top10**：仅活跃报警，`GROUP BY point_id ORDER BY count DESC LIMIT 10`
4. **小时趋势**：`EXTRACT(HOUR FROM point_time)`，按小时聚合活跃报警数

### 3.3 设备报警列表（GET /api/alarms/devices）

```
SELECT DISTINCT a.device_id, d.device_name,
       COUNT(*) as alarm_count,
       COUNT(*) FILTER (WHERE a.point_value = 1) as active_count,
       MAX(a.point_time) as last_alarm_time
FROM device_alarm_info a
LEFT JOIN device_info d ON a.device_id = d.device_id
GROUP BY a.device_id, d.device_name
ORDER BY alarm_count DESC
```

---

## 四、AI 分析引擎

### 4.1 异常检测（AnomalyDetector）

#### 检测流程

```
1. 计算基线（calculate_baselines）
   ├── 对每个参数计算 5th/95th 百分位
   ├── IQR 过滤后的均值、标准差、中位数
   └── 去除异常值后建立稳健基线

2. 检测异常（detect_anomalies）
   └── 对每个数据点检查 4 种异常类型

3. 预测报警（predict_alarms）
   ├── 线性回归计算最近 20 个点的趋势斜率
   ├── 估算到达报警阈值的时间
   └── 根据距阈值距离计算概率
```

#### 异常类型

| 类型 | 判定条件 | 严重度 |
|------|---------|--------|
| **越限** | 超出 alarm_low/alarm_high | 超过 90%/110% 阈值 → 严重；否则 → 高 |
| **漂移** | 超出正常范围但未达报警阈值 | 中 |
| **突变** | 相邻值变化 >15% | >30% → 高；否则 → 中 |
| **卡死** | 最近 11 个值中 <=2 个唯一值 | 低 |

#### 报警预测

- 对每个报警-参数关联（`ALARM_PARAMETER_MAPPING`），计算趋势斜率
- 若值已超出正常范围且朝报警阈值移动，估算触发时间
- 输出：预测报警类型、概率、预计触发时间、影响因素、建议措施

### 4.2 健康评估（HealthDashboard）

#### 评分机制

```
1. 计算参数健康分（0-100）
   ├── 90-100：在最优范围内（越接近最优值分越高）
   ├── 70-90：正常但非最优
   ├── 40-70：接近报警范围
   └── 0-40：超出报警范围

2. 判断趋势（线性回归最近 10 个值）
   └── 上升 / 下降 / 稳定

3. 识别风险因素
   └── 低值 / 高值 / 接近报警阈值 / 不利趋势 / 高波动

4. 加权聚合（PARAMETER_WEIGHTS）
   ├── 主机功率：20%
   ├── 温度参数：各 12%
   ├── 风压参数：各 10%
   └── ...
```

#### 健康等级

| 等级 | 分数范围 |
|------|---------|
| Excellent | 90-100 |
| Good | 75-89 |
| Fair | 60-74 |
| Warning | 40-59 |
| Critical | 0-39 |

### 4.3 故障预测（FaultPredictor）

#### 特征计算

对每个参数计算：当前值、均值、标准差、最小/最大值、基线统计、趋势、斜率、最大变化率。

#### 故障模式检测

覆盖 6 种故障类型，每种模式定义了特征参数和检测条件：

| 故障类型 | 特征参数 | 检测方式 |
|---------|---------|---------|
| **Mechanical**（机械） | 振动、功率、转速 | 趋势 + 阈值 |
| **Electrical**（电气） | 电流、电压 | 波动 + 阈值 |
| **Thermal**（热） | 温度参数 | 趋势 + 差分 |
| **Pressure**（压力） | 风压、压差 | 上升检测 + 阈值 |
| **Material**（物料） | 进料量 | 消耗率检测 |
| **Filter**（过滤） | 布袋压差、过滤器压差 | 压差上升 + 真空范围 |

#### 匹配评分规则

| 检测方式 | 得分 |
|---------|------|
| 多参数趋势同步上升 | +0.4 |
| 标准差超限 | +0.3 |
| 最大-最小差值超限 | +0.3 |
| 参数比值异常 | +0.5 |
| 单参数超阈值 | +0.3 |
| 偏离基线 | +0.3 |
| 压力上升趋势 | +0.5 |
| 物料消耗率异常 | +0.5 |
| 真空范围异常 | +0.5 |

匹配分 > 0.3 即判定为该故障模式命中。

#### 剩余寿命估算

对耗材参数（布袋压差、过滤器压差），基于线性回归斜率估算到达更换阈值的时间（假设 5 分钟采样间隔）。

### 4.4 能效优化（EnergyOptimizer）

```
1. 功率统计：平均/最大/最小功率、总能耗
2. 效率评分（100分制）
   ├── 基础 100 分
   ├── 功率变异系数 > 0.1 → -10~-20
   ├── 空载时间比例 → -30 × 比例
   ├── 过载时间比例 → -25 × 比例
   ├── 最优范围运行 → +10 × 比例
   └── 工况协调惩罚 → 最多 -15
3. 最优运行时段识别（按小时分组，效率 >= 85 的时段）
4. 优化建议（6类）：空载优化、负载均衡、稳定性提升、温度协调、风压平衡、过滤维护
```

---

## 五、报警分析 API 核心流程

### 5.1 执行报警分析（POST /api/alarms/analysis）

这是报警分析最重要的端点，合并 SQL 统计与 AI 检测：

```
1. 确定时间范围
   ├── 根据 start_date / end_date / report_type 计算查询区间
   └── 日报/周报/月报对应不同默认时长

2. SQL 统计（PostgresDB.get_alarm_statistics）
   ├── 总量 + 活跃数
   ├── 按设备 Top10
   ├── 按类型 Top10
   └── 按小时趋势

3. AI 异常检测（FactoryAIAnalyzer.run_anomaly_detection）
   ├── 加载历史时序数据
   ├── 运行 AnomalyDetector.detect_anomalies()
   ├── 运行 AnomalyDetector.predict_alarms()
   └── 统计异常总数、严重度分布

4. 保存结果
   ├── 写入 alarm_analysis_{daily,weekly,monthly} 表
   ├── ON CONFLICT (report_date, device_id) DO UPDATE（自动覆盖）
   └── statistics + analysis + query_params 三个 JSONB 字段

5. 返回合并结果
   ├── statistics：SQL 聚合结果
   ├── analysis：AI 检测结果
   ├── query：查询参数回显
   └── saved: true/false
```

### 5.2 分析结果存储

三张结构相同的表，通过 `UNIQUE(report_date, device_id)` 约束实现同日期覆盖：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| report_date | DATE | 报告日期 |
| device_id | VARCHAR(50) | 设备ID |
| statistics | JSONB | SQL 统计结果 |
| analysis | JSONB | AI 分析结果 |
| query_params | JSONB | 查询参数 |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

---

## 六、完整 API 接口

### 6.1 报警记录（/api/alarms）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/alarms` | 分页查询报警记录 |
| GET | `/api/alarms/statistics` | 报警统计聚合 |
| GET | `/api/alarms/devices` | 有报警的设备列表 |
| GET | `/api/alarms/types` | 报警类型定义 |

### 6.2 报警分析（/api/alarms/analysis）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/alarms/analysis` | 执行报警分析（SQL + AI） |
| GET | `/api/alarms/analysis/history` | 分析历史列表 |
| GET | `/api/alarms/analysis/detail` | 分析详情 |

### 6.3 设备分析（/api/device_analysis）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/device_analysis/modules` | 可用分析模块列表 |
| POST | `/api/device_analysis` | 执行指定模块分析 |

### 6.4 任务管理（/api/jobs）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jobs` | 任务列表 |
| GET | `/api/jobs/summary` | 任务统计摘要 |
| GET | `/api/jobs/scheduled` | 定时任务列表 |
| GET | `/api/jobs/{job_name}` | 指定任务历史 |

---

## 七、前端集成

### 7.1 报警分析页（AlarmAnalysis.vue）

三栏布局：
- **左侧（1/3）**：查询面板（报告类型、设备、日期范围）+ 历史记录列表
- **右侧（2/3）**：
  - 4 个汇总卡片（总报警、活跃报警、异常检测数、报警预测数）
  - 报警类型 Top10 + 严重度分布柱状图
  - 按小时趋势图
  - AI 分析原始 JSON 详情

### 7.2 报警记录页（Alarms.vue）

- 4 个统计卡片（总量、活跃、设备数、类型数）
- 筛选面板（设备、关键词、日期、仅活跃）
- 分页报警表格（时间、设备、报警名、状态、点位ID）
- 触发状态带红色闪烁圆点动画

---

## 八、两个编排器

### 8.1 FactoryAIAnalyzer（main.py）

- 用于 `/api/alarms/analysis` 端点
- 使用硬编码配置（默认设备 102000018415）
- 加载数据后运行 4 个 AI 模块

### 8.2 PredictiveMaintenance（predictive_maintenance.py）

- 用于预测性维护报告和 `/api/device_analysis` 端点
- 动态从 `point_config.py` 加载设备配置
- 支持球磨机和合膏机两种设备类型
- 根据设备类型选择不同的阈值、报警映射、故障模式

---

## 九、定时调度

独立调度脚本 `scheduler.py`（AnalysisScheduler，含 anomaly_detection / health_check /
fault_prediction / energy_analysis 四个固定间隔 job）已移除（2026-07，从未部署运行）。
定时任务统一由「系统管理 → 任务管理」（`routes/system_jobs.py` + `core/scheduler.py`）调度；
四类分析能力仍通过 `/api/device_analysis`（设备诊断页）按需调用，或由预测性维护报告集成调用。

---

## 十、关键设计说明

1. **数据双义性**：`device_alarm_info.point_value` 对报警点位是 0/1，对工艺参数是实际数值。`data_loader.py` 默认使用 `use_logic_names=True` 将点位 ID 转为中文逻辑名。
2. **分析结果自动覆盖**：`ON CONFLICT (report_date, device_id) DO UPDATE`，同日期同设备重复执行覆盖之前结果。
3. **阈值配置驱动**：所有阈值、报警映射、故障模式均在 `point_config.py` 中定义，新增设备只需扩展该配置。
4. **设备 ID 参考**：

| 设备 ID | 设备名称 | 类型 |
|---------|---------|------|
| 102000018415 | 正1#金帆球磨机 | 球磨机 |
| 102000000996 | 正2#衡远合膏机 | 合膏机 |
