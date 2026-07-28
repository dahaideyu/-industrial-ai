# 预测性维护系统指南

> 本文档说明如何将 `docs/江西两台设备点位信息(1).xlsx` 与 PostgreSQL 数据库对应，实现设备的预测性维护能力。

---

## 1. 背景与目标

### 1.1 数据来源

- **Excel 点位说明**: `docs/江西两台设备点位信息(1).xlsx`
  - 定义了两台设备的报警参数（Alarm/AlarmMix）和工艺参数（Tec_xxx）
  - 包含点位标识、中文名称、备注说明
- **PostgreSQL 实时数据**: `device_alarm_info` 表
  - 存储了设备的实时/历史点位数据（`point_id`, `point_value`, `point_time`）
  - 但原始 `point_info` 表只包含报警参数，**缺失工艺参数定义**

### 1.2 核心问题

预测模块（异常检测、故障预测、健康看板）使用**中文参数名**（如"前段温度"、"主机功率"），而数据库使用**英文 point_id**（如 `Tec_Qd_Tep`、`Tec_Power`）。

**目标**: 建立 `point_id ↔ 中文参数名 ↔ 故障模式` 的完整映射，实现从数据库读取数据到预测分析的全自动流转。

---

## 2. 设备与点位总览

### 2.1 正1#金帆球磨机

| 属性 | 值 |
|------|-----|
| 设备编号 | `102000018415` |
| 设备类型 | `ball_mill` |
| MQTT Topic | `Alarm/chaowei/jxcw` |

#### 工艺参数映射

| point_id | 中文逻辑名（预测模块使用） | Excel 原始名称 |
|----------|------------------------|--------------|
| `Tec_Bd_Yc` | 布袋压差 | 布袋压差 |
| `Tec_Ffy` | 负压风压 | 负压风压显示 |
| `Tec_Glq_Yc` | 过滤器压差 | 过滤器压差 |
| `Tec_Hd_Tep` | 后段温度 | 后段温度显示 |
| `Tec_Power` | 主机功率 | 功率显示 |
| `Tec_Qd_Tep` | 前段温度 | 前段温度显示 |
| `Tec_Qf_Tep` | 铅粉温度 | 铅粉温度 |
| `Tec_Qlc_Weight` | 铅粒仓重量 | 铅粒仓重量显示 |
| `Tec_Zd_Tep` | 中段温度 | 中段温度显示 |
| `Tec_Zfy` | 正压风压 | 正压风压显示 |

#### 报警参数（部分示例）

| point_id | 报警名称 |
|----------|---------|
| `Alarm1` | 负风风压下限报警 |
| `Alarm2` | 负风风压上限报警 |
| `Alarm6` | 布袋压差报警 |
| `Alarm10` | 后温下限报警 |
| `Alarm16` | 电机功率下限报警 |
| ... | ...（共 52 个） |

---

### 2.2 正2#衡远合膏机

| 属性 | 值 |
|------|-----|
| 设备编号 | `102000000996` |
| 设备类型 | `mixer` |
| MQTT Topic | `Alarm/chaowei/jxcw` |

#### 工艺参数映射

| point_id | 中文逻辑名 | Excel 原始名称 |
|----------|-----------|--------------|
| `Tec_DQD_DH` | 合膏阶段状态 | 合膏阶段状态 |
| `Tec_End` | 合膏结束标志位 | 合膏结束标志位 |
| `Tec_Hg_tep` | 合膏温度 | 合膏温度 |
| `Tec_Hg_tep_Max` | 合膏最高温度 | 合膏最高温度 |
| `Tec_lead_Actual_weight` | 铅实际重量 | 铅实际重量 |
| `Tec_lead_Real_weight` | 铅实时重量 | 铅实时重量 |
| `Tec_Sszkd` | 合膏实时真空度 | 合膏实时真空度 |
| `Tec_sour_Actual_weight` | 酸实际重量 | 酸实际重量 |
| `Tec_sour_Real_weight` | 酸实时重量 | 酸实时重量 |
| `Tec_Water_Actual_weight` | 水实际重量 | 水实际重量 |
| `Tec_Water_Real_weight` | 水实时重量 | 水实时重量 |

#### 报警参数（部分示例）

| point_id | 报警名称 |
|----------|---------|
| `AlarmMix1` | 请加液态辅料 |
| `AlarmMix2` | 自动合膏未完 |
| `AlarmMix10` | 进粉超时报警 |
| `AlarmMix15` | 温度超温报警 |
| `AlarmMix20` | 进料超重 |
| ... | ...（共 37 个） |

---

## 3. 系统架构与数据流

```
┌─────────────────────────────────────────────────────────────┐
│                    Excel 点位说明文件                        │
│         (报警参数 + 工艺参数的中文定义)                       │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              ai_analysis/point_config.py                     │
│  ├─ PROCESS_POINT_LOGIC_NAMES: point_id → 中文逻辑名         │
│  ├─ ALARM_POINT_NAMES: point_id → 报警名称                   │
│  ├─ PARAMETER_THRESHOLDS: 各参数的正常/报警阈值              │
│  ├─ ALARM_PARAMETER_MAPPING: 报警与工艺参数关联              │
│  └─ FAULT_PATTERN_CONFIG: 故障模式定义（按设备）              │
└───────────────────────┬─────────────────────────────────────┘
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
┌──────────────────┐      ┌──────────────────────┐
│ sync_excel_to_   │      │   data_loader.py     │
│ postgres.py      │      │   (数据加载)          │
│ (同步到数据库)    │      │                      │
└────────┬─────────┘      │  1. 从 PostgreSQL    │
         │                │     查询 device_alarm_info
         ▼                │  2. 用 point_config  │
┌──────────────────┐      │     映射中文名        │
│   point_info     │      │  3. 返回             │
│   (数据库表)      │      │     {"前段温度": df} │
│ 补充工艺参数定义  │      └──────────┬───────────┘
└──────────────────┘                 │
                                     ▼
                    ┌────────────────────────────────┐
                    │     预测性维护分析模块          │
                    │  ├─ anomaly_detector.py        │
                    │  │   异常检测（越限/突变/卡死）  │
                    │  ├─ health_dashboard.py        │
                    │  │   设备健康评分（0~100）       │
                    │  ├─ fault_predictor.py         │
                    │  │   故障模式匹配 & 预测        │
                    │  └─ energy_optimizer.py        │
                    │      能耗分析与优化建议         │
                    └───────────────┬────────────────┘
                                    │
                                    ▼
                    ┌────────────────────────────────┐
                    │  predictive_maintenance.py     │
                    │      综合报告 & JSON 导出       │
                    └────────────────────────────────┘
```

---

## 4. 核心模块说明

### 4.1 point_config.py — 映射配置中心

所有 Excel 与数据库的映射关系集中在此文件，便于维护和扩展。

**关键函数**:

```python
from point_config import (
    get_logic_name,           # point_id → 中文逻辑名
    get_display_name,         # point_id → Excel 显示名
    get_alarm_name,           # point_id → 报警名称
    get_device_config_for_predictor,  # 获取设备完整预测配置
)

# 示例
name = get_logic_name("102000018415", "Tec_Qd_Tep")
# 返回: "前段温度"

config = get_device_config_for_predictor("102000018415")
# 返回: {
#   "device_id": "102000018415",
#   "device_name": "正1#金帆球磨机",
#   "thresholds": {...},
#   "alarm_mapping": {...},
#   "fault_patterns": {...}
# }
```

---

### 4.2 sync_excel_to_postgres.py — 同步脚本

**作用**: 将 Excel 中的工艺参数点位信息补充到 `point_info` 表。

**执行方式**:

```bash
cd ai_analysis

# 预览（不写入）
python sync_excel_to_postgres.py --dry-run

# 执行同步
python sync_excel_to_postgres.py
```

**同步结果**:

- 正1#金帆球磨机: 补充 10 个工艺参数
- 正2#衡远合膏机: 补充 11 个工艺参数
- 合计: 21 个点位已同步至 `point_info`

---

### 4.3 data_loader.py — 数据加载器

**增强功能**: `load_history_data()` 新增 `use_logic_names` 参数。

```python
from data_loader import DataLoader

loader = DataLoader()

# 自动将 point_id 映射为中文逻辑名
history = loader.load_history_data(
    device_id="102000018415",
    hours=24,
    use_logic_names=True,   # 默认为 True
)

# 返回: {"前段温度": DataFrame, "主机功率": DataFrame, ...}
```

---

### 4.4 predictive_maintenance.py — 预测性维护主入口

**功能**: 整合所有分析模块，一键生成预测性维护报告。

**使用方式**:

```bash
cd ai_analysis

# 默认分析正1#金帆球磨机（最近24小时）
python predictive_maintenance.py

# 分析合膏机
python predictive_maintenance.py --device 102000000996

# 分析过去48小时并导出 JSON
python predictive_maintenance.py --hours 48 --json --output report.json
```

**支持设备列表**:

| 设备ID | 设备名称 |
|--------|---------|
| `102000018415` | 正1#金帆球磨机 |
| `102000000996` | 正2#衡远合膏机 |

---

## 5. 故障模式配置

### 5.1 正1#金帆球磨机

| 故障类型 | 关联参数 | 检测逻辑 |
|---------|---------|---------|
| **温度异常** | 前段/中段/后段/铅粉温度 | 多参数持续上升、温差 > 20℃、波动过大 |
| **风压系统异常** | 正压风压、负压风压 | 正负风压比失衡、负压过低、正压过高 |
| **机械部件异常** | 主机功率 | 功率波动大、相对基线异常升降 |
| **过滤系统堵塞** | 布袋压差、过滤器压差 | 压差持续上升、超过阈值 |
| **物料系统异常** | 铅粒仓重量 | 消耗速率异常、变化过小（卡料） |

### 5.2 正2#衡远合膏机

| 故障类型 | 关联参数 | 检测逻辑 |
|---------|---------|---------|
| **温度异常** | 合膏温度、合膏最高温度 | 温度持续上升、温差过大 |
| **真空系统异常** | 合膏实时真空度 | 真空度超出正常范围 |
| **称量系统异常** | 水/酸/铅实时重量 | 重量波动大、漂移异常 |

---

## 6. 分析模块详解

### 6.1 异常检测 (anomaly_detector.py)

**检测类型**:

| 异常类型 | 说明 | 严重程度 |
|---------|------|---------|
| 越限 | 超出报警上下限 | 高/严重 |
| 漂移 | 偏离正常范围 | 中 |
| 突变 | 单点变化率 > 15% | 高 |
| 卡死 | 连续11个值相同 | 低 |

**报警预测**: 基于线性回归趋势，预测工艺参数何时会触发关联报警。

---

### 6.2 健康看板 (health_dashboard.py)

**评分维度**:

- 各参数健康分（0~100），基于与最优区间的偏离程度
- 综合健康指数 = 加权平均
- 状态等级: 优秀(90+) / 良好(75-89) / 一般(60-74) / 警告(40-59) / 危险(0-39)

**输出示例**:

```
综合健康指数: 85.3/100 [OK] 良好
[##########################################--------]

参数状态分布: 优秀:8 良好:0 一般:0 警告:1 危险:1

各参数健康状态:
参数           当前值      健康分  状态    趋势
------------------------------------------------------------------
布袋压差         69.0       91  良好    下降
过滤器压差      131.0       28  危险    稳定
主机功率        101.0       96  优秀    下降
...
```

---

### 6.3 故障预测 (fault_predictor.py)

**核心能力**:

1. **特征计算**: 对每项参数计算当前值、均值、标准差、趋势、斜率、变化率
2. **模式匹配**: 与 `FAULT_PATTERN_CONFIG` 中定义的故障模式进行匹配
3. **剩余寿命估计**: 对压差类参数，基于趋势线性外推估计到达更换阈值的时间

**预测输出**:

```
[1] 过滤系统堵塞
    概率: 100%  严重程度: 严重
    预计发生时间: 2:00:00
    置信度: 90%
    相关参数: 布袋压差, 过滤器压差
    预警信号:
      - 过滤器压差: 上升趋势
      - 过滤器压差: 当前值偏高
    建议措施:
      * 清理或更换布袋
      * 清理或更换过滤器
      * 检查反吹系统
```

---

### 6.4 能耗优化 (energy_optimizer.py)

**分析内容**:

- 平均/最大/最小功率、总能耗、功率波动
- 空载时间比例、过载时间比例
- 最佳运行时段识别
- 温度协调性、风压平衡性评估

**优化建议类型**:

- 空载优化（调整生产排程）
- 负载均衡（分散高峰负载）
- 稳定运行（检查进料/PID参数）
- 温度优化（检查加热/冷却系统）
- 风压优化（调整风机频率）
- 维护提醒（压差上升预警）

---

## 7. 数据库表结构

### 7.1 device_info

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | varchar | 设备编号（如 `102000018415`） |
| `device_name` | varchar | 设备名称 |

### 7.2 point_info（已同步工艺参数）

| 字段 | 类型 | 说明 |
|------|------|------|
| `point_id` | varchar | 点位标识（如 `Tec_Qd_Tep`, `Alarm1`） |
| `point_name` | varchar | 点位中文名称 |
| `belong_devide` | varchar | 所属设备ID |
| `remark` | varchar | 备注（"工艺参数" 或 "Alarm1=1为报警 =0正常"） |

### 7.3 device_alarm_info（实时数据）

| 字段 | 类型 | 说明 |
|------|------|------|
| `device_id` | varchar | 设备编号 |
| `device_status` | varchar | 在线状态 |
| `point_id` | varchar | 点位标识 |
| `point_value` | int | 点位数值 |
| `point_time` | timestamp | 采集时间 |
| `raw_json` | jsonb | 原始上报JSON |

---

## 8. 扩展指南

### 8.1 新增设备

1. **在 Excel 中增加新设备的 Sheet**
2. **更新 `point_config.py`**:
   - 在 `DEVICES` 中添加设备信息
   - 在 `PROCESS_POINT_LOGIC_NAMES` / `ALARM_POINT_NAMES` 中添加点位映射
   - 在 `PARAMETER_THRESHOLDS` / `FAULT_PATTERN_CONFIG` 中添加预测配置
3. **运行同步脚本**: `python sync_excel_to_postgres.py`
4. **验证**: `python predictive_maintenance.py --device <新设备ID>`

### 8.2 调整阈值

直接修改 `point_config.py` 中的 `PARAMETER_THRESHOLDS`:

```python
"正1#金帆球磨机": {
    "前段温度": (180, 220, 150, 230),  # (正常下限, 正常上限, 报警下限, 报警上限)
    "主机功率": (90, 106, 80, 110),
    ...
}
```

### 8.3 新增故障模式

在 `point_config.py` 的 `FAULT_PATTERN_CONFIG` 中增加:

```python
"102000018415": {
    ...
    "new_fault": {
        "name": "新故障类型",
        "point_ids": ["Tec_Xxx"],
        "logic_names": ["中文参数名"],
        "thresholds": {"std_max": 10, "rise_count": 1},
        "preventive_actions": ["建议措施1", "建议措施2"],
    },
}
```

---

## 9. 文件清单

| 文件路径 | 作用 |
|---------|------|
| `docs/江西两台设备点位信息(1).xlsx` | 原始点位定义 Excel |
| `docs/predictive_maintenance_guide.md` | 本文档 |
| `ai_analysis/point_config.py` | **新增** 点位映射与预测配置中心 |
| `ai_analysis/sync_excel_to_postgres.py` | **新增** Excel → 数据库同步脚本 |
| `ai_analysis/predictive_maintenance.py` | **新增** 预测性维护主入口 |
| `ai_analysis/data_loader.py` | **修改** 支持 point_id → 中文名映射 |
| `ai_analysis/fault_predictor.py` | **修改** 支持配置化故障模式检测 |
| `ai_analysis/anomaly_detector.py` | **修改** 支持动态传入阈值配置 |
| `ai_analysis/health_dashboard.py` | **修改** 支持动态传入权重/区间配置 |
| `ai_analysis/energy_optimizer.py` | **修改** 支持动态传入能耗阈值配置 |

---

## 10. 快速命令速查

```bash
# 进入分析模块目录
cd ai_analysis

# 同步 Excel 点位到数据库
python sync_excel_to_postgres.py

# 分析球磨机（最近24小时）
python predictive_maintenance.py

# 分析合膏机（最近24小时）
python predictive_maintenance.py --device 102000000996

# 分析过去48小时并导出 JSON
python predictive_maintenance.py --hours 48 --json --output report.json

# 单独测试数据加载
python -c "from data_loader import DataLoader; \
  h = DataLoader().load_history_data('102000018415', hours=2); \
  print(list(h.keys()))"
```

---

*文档版本: v1.0*  
*更新日期: 2026-04-29*  
*维护模块: `ai_analysis/predictive_maintenance.py`*
