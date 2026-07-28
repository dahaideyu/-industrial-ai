# 预测性维护报告系统

> 基于 AI 分析的工业设备预测性维护报告自动生成系统，支持日报/周报/月报三种周期，集成异常检测、健康评估、故障预测三大分析模块，通过 LLM 生成结构化维护建议。

---

## 一、系统架构

### 1.1 整体数据流

```
PostgreSQL / TimescaleDB（历史数据 + 报警事件）
    │
    ▼
DataAggregator（数据聚合）
    │  ├── 加载设备历史时序数据
    │  ├── 加载报警事件
    │  └── 计算报警统计、趋势、环比对比
    │
    ▼
AnalysisIntegrator（AI 分析编排）
    │  ├── AnomalyDetector  → 异常检测 & 报警预测
    │  ├── HealthDashboard  → 健康评分 & 风险评估
    │  └── FaultPredictor   → 故障预测 & 预防措施
    │
    ▼
MaintenanceReportGenerator（报告生成）
    │  ├── 构建提示词数据（结构化 JSON）
    │  ├── 加载报告模板（daily/weekly/monthly）
    │  └── 调用 LLM 生成 Markdown 报告
    │
    ▼
PostgreSQL 存储（device_report / workshop_report_summary / report_generation_job）
    │
    ▼
FastAPI Routes → Vue.js 前端
```

### 1.2 模块目录结构

```
backend/modules/maintenance_report/
├── __init__.py                  # 模块入口，导出 maintenance_report_router
├── routes.py                    # API 路由定义
├── models/
│   └── schemas.py               # Pydantic 请求/响应模型
├── services/
│   ├── data_aggregator.py       # 数据聚合服务
│   ├── analysis_integrator.py   # AI 分析编排服务
│   ├── report_generator.py      # 报告生成核心服务
│   └── scheduler.py             # APScheduler 定时调度
└── prompts/
    ├── loader.py                # 模板加载器
    ├── device_daily_report.txt  # 日报提示词模板
    ├── device_weekly_report.txt # 周报提示词模板
    └── device_monthly_report.txt# 月报提示词模板
```

---

## 二、核心流程详解

### 2.1 报告生成流程

以单台设备报告为例（`MaintenanceReportGenerator.generate_device_report()`）：

```
1. 确定时间范围
   ├── 日报：report_date 前 24 小时
   ├── 周报：report_date 前 7 天
   └── 月报：report_date 前 30 天

2. 数据聚合（DataAggregator.aggregate_device_data）
   ├── 从 PostgreSQL/TimescaleDB 加载历史时序数据
   ├── 加载该时间段内的报警事件
   └── 计算报警统计（报警次数、类型分布、报警率）

3. AI 分析（AnalysisIntegrator.analyze）
   ├── 异常检测：spike / drift / threshold / pattern / frozen
   ├── 健康评估：各参数加权评分 → 总体健康分（0-100）
   └── 故障预测：6 类故障模式检测 + 概率评估

4. 环比数据（周报/月报专属）
   ├── 上期报警数量对比
   ├── 报警率变化
   └── 趋势方向（上升/下降/持平）

5. 构建 Prompt 数据
   ├── device_info、period、alarm_statistics
   ├── health_assessment、anomaly_detection、fault_prediction
   ├── maintenance_suggestions、comparison
   └── 序列化为 JSON 注入模板 {data_sources} 占位符

6. 调用 LLM 生成报告
   ├── ChatOpenAI（LangChain）
   ├── temperature=0.7, timeout=600s
   └── 输出 Markdown 格式报告

7. 存储到 PostgreSQL
   ├── device_report 表：报告内容 + 结构化字段
   └── 返回报告 ID 和摘要
```

### 2.2 批量生成

- 通过 `generate_batch_reports()` 批量处理多台设备
- 使用 `asyncio.Semaphore(5)` 控制并发上限
- 每台设备独立生成，互不影响

### 2.3 流式生成（SSE）

- `generate_device_report_stream()` 支持实时流式输出
- 后台线程运行 LLM 流式调用，通过 `Queue` 桥接到 SSE
- 空闲时发送心跳包保持连接
- 流式完成后自动保存完整报告

---

## 三、AI 分析模块

### 3.1 异常检测（AnomalyDetector）

| 异常类型 | 说明 |
|---------|------|
| spike | 参数值突增/突降 |
| drift | 参数值持续偏移 |
| threshold | 超出正常阈值范围 |
| pattern | 运行模式异常 |
| frozen | 数据冻结（长时间无变化） |

输出：
- `Anomaly` 列表：时间戳、参数、类型、严重度、阈值、描述
- `AlarmPrediction` 列表：预测报警、概率、预计触发时间、建议

### 3.2 健康评估（HealthDashboard）

**评分机制**：各参数独立评分（0-100），按权重聚合为总体健康分。

关键参数权重示例：

| 参数 | 权重 |
|------|------|
| 主机功率 | 0.20 |
| 中段温度 | 0.12 |
| 布袋压差 | 0.12 |
| ... | ... |

**健康等级**：

| 等级 | 分数范围 |
|------|---------|
| Excellent | 90-100 |
| Good | 75-89 |
| Fair | 60-74 |
| Warning | 40-59 |
| Critical | 0-39 |

输出：
- 总体健康分和等级
- 各参数评分
- 高风险参数列表
- 维护建议

### 3.3 故障预测（FaultPredictor）

覆盖 6 种故障类型：

| 故障类型 | 说明 |
|---------|------|
| Mechanical | 机械故障（振动、磨损、轴承） |
| Electrical | 电气故障（电流、电压异常） |
| Thermal | 热故障（温度异常） |
| Pressure | 压力故障（压力异常） |
| Material | 物料故障（堵塞、泄漏） |
| Filter | 过滤故障（压差、堵塞） |

每种故障模式定义了：
- 特征参数列表
- 检测条件
- 预防措施

输出：
- 故障类型、概率、严重度
- 预计发生时间
- 相关参数、预警信号
- 预防措施

### 3.4 风险等级判定

由 `AnalysisIntegrator._create_summary()` 计算：

| 风险等级 | 判定条件 |
|---------|---------|
| critical | 健康分 < 40 OR 高风险故障 >= 2 OR 严重异常 >= 10 |
| high | 健康分 < 60 OR 高风险故障 >= 1 OR 严重异常 >= 5 |
| medium | 健康分 < 75 OR 严重异常 >= 2 |
| low | 其他情况 |

---

## 四、定时调度

### 4.1 调度配置

使用 APScheduler（AsyncIOScheduler）实现定时任务：

| 报告类型 | Cron 表达式 | 执行时间 |
|---------|------------|---------|
| 日报 | `hour=1, minute=0` | 每天 01:00 |
| 周报 | `day_of_week='mon', hour=2, minute=0` | 每周一 02:00 |
| 月报 | `day=1, hour=3, minute=0` | 每月 1 日 03:00 |

### 4.2 启用方式

在 `.env` 中设置：

```bash
ENABLE_REPORT_SCHEDULER=true
```

调度器在 FastAPI `lifespan` 中自动启动。未启用时，前端 Jobs 页面会显示提示。

### 4.3 手动触发

```
POST /api/maintenance-reports/schedule/trigger
Body: { "report_type": "daily", "report_date": "2026-05-09" }
```

### 4.4 调度执行流程

```
1. 创建 job 记录（report_generation_job + analysis_job_run）
2. 遍历所有设备，逐台生成报告
3. 每台完成后更新进度
4. 全部完成后生成车间级汇总（workshop_report_summary）
5. 标记 job 完成状态
```

---

## 五、LLM 提示词模板

### 5.1 模板体系

| 模板 | 角色 | 特点 |
|------|------|------|
| 日报 | 资深工业设备维护工程师 | 聚焦当日异常、次日关注点 |
| 周报 | 维护工程师 + 趋势分析 | 增加环比对比、下周维护计划 |
| 月报 | 资深工程师 + 数据分析师 | 深度根因分析、生命周期管理、长期改进建议 |

### 5.2 数据注入方式

模板中使用 `{data_sources}` 占位符，运行时替换为结构化 JSON：

```json
{
  "device_info": { "device_id": "...", "device_name": "...", "workshop": "..." },
  "period": { "start": "...", "end": "...", "type": "daily" },
  "alarm_statistics": { "alarm_count": 12, "alarm_types": {...}, "alarm_rate": 0.05 },
  "health_assessment": { "overall_score": 78, "status": "Good", "parameter_scores": {...} },
  "anomaly_detection": { "anomalies": [...], "alarm_predictions": [...] },
  "fault_prediction": { "faults": [...], "high_risk_faults": [...] },
  "maintenance_suggestions": [...],
  "comparison": { "alarm_count_change": "+15%", "alarm_rate_change": "+0.02", "trend": "上升" }
}
```

### 5.3 LLM 配置

| 参数 | 值 |
|------|-----|
| Provider | 环境变量 `PROVIDER`（deepseek/qwen3/openai/local_qwen3） |
| Temperature | 0.7 |
| Timeout | 600s |
| Max Retries | 2 |

---

## 六、数据存储

### 6.1 device_report 表（设备级报告）

| 字段分类 | 关键字段 |
|---------|---------|
| 基本信息 | report_type, report_date, device_id, device_name, workshop_id |
| 报警统计 | alarm_count, alarm_types(JSONB), alarm_duration_seconds, alarm_rate |
| 健康评估 | health_score, health_status, health_trend, parameter_health(JSONB) |
| 故障预测 | fault_predictions(JSONB), risk_level, estimated_issues(JSONB) |
| 维护建议 | maintenance_suggestions(JSONB), urgent_actions(JSONB), scheduled_maintenance(JSONB) |
| AI 内容 | report_content(TEXT), report_summary(前 500 字) |
| 环比趋势 | comparison_data(JSONB), trend_data(JSONB) |
| 元数据 | generated_by, generation_time_seconds, llm_model |

索引：report_date, report_type, device_id, workshop_id, health_score, risk_level

### 6.2 workshop_report_summary 表（车间级汇总）

| 字段 | 说明 |
|------|------|
| devices_critical/warning/fair/good/excellent | 各健康等级设备数 |
| avg/min/max health_score | 健康分统计 |
| total_alarms, top_alarm_devices, top_alarm_types | 报警汇总 |

### 6.3 report_generation_job 表（任务执行记录）

| 字段 | 说明 |
|------|------|
| job_type, job_status | 任务类型和状态 |
| total_devices, processed_devices, failed_devices | 进度跟踪 |
| trigger_type, triggered_by | 触发方式（scheduled/manual） |
| started_at, completed_at | 执行时间 |
| error_message, error_details | 错误信息 |

---

## 七、API 接口

所有接口前缀：`/api/maintenance-reports`

### 7.1 报告生成

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/generate` | 生成单台设备报告（同步） |
| POST | `/generate/stream` | 流式生成报告（SSE） |
| POST | `/generate/batch` | 批量生成报告（后台任务） |

### 7.2 报告查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/list` | 报告列表（支持分页、过滤） |
| GET | `/detail/{report_id}` | 报告详情 |
| DELETE | `/delete/{report_id}` | 删除报告 |
| GET | `/summary/{report_type}/{report_date}` | 日期汇总统计 |
| GET | `/workshop-summary` | 车间汇总 |

### 7.3 调度管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/schedule/trigger` | 手动触发报告生成 |
| GET | `/schedule/status` | 调度器状态 |
| GET | `/jobs` | 任务列表 |
| GET | `/jobs/{job_id}` | 任务详情 |
| GET | `/templates` | 可用模板列表 |

### 7.4 设备查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/devices` | 设备列表（可按车间过滤） |

---

## 八、前端集成

| 页面 | 文件 | 功能 |
|------|------|------|
| Jobs | `frontend/src/views/Jobs.vue` | 任务管理、手动触发生成、调度状态 |
| Dashboard | `frontend/src/views/Dashboard.vue` | 设备健康概览、快捷入口 |
| Report | `frontend/src/views/Report.vue` | 通用报告生成（非预测性维护） |

当前前端仅 `triggerReportGeneration` 接入，报告列表/详情/车间汇总等查询接口尚待前端页面开发。

---

## 九、已知限制

1. **报警时长估算**：每条报警默认按 5 分钟计算，非真实持续时间
2. **健康趋势**：周报/月报中的上期健康分基于启发式估算（`prev_score = current_score + alarm_count_change * -0.5`），非实际历史评分
3. **车间汇总模板**：`loader.py` 已映射但对应 `.txt` 模板文件尚未创建
4. **调度器串行执行**：定时任务逐台设备顺序生成，未使用并发
5. **前端覆盖不全**：仅触发接口接入，查询类接口无前端页面
