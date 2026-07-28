# 报警分析 API 文档

## 接口概述

报警分析模块提供基于时间段的设备报警统计与 AI 异常检测能力，支持时间段选择和设备筛选。分析结果按报告类型（日报/周报/月报）存入数据库，同日期同设备重复执行自动覆盖。

**基础路径**: `/api/alarms`

---

## 接口列表

### 1. 执行报警分析

**`POST /api/alarms/analysis`**

合并 SQL 统计与 AI 异常检测结果，支持时间段选择。同时间段再次执行会覆盖之前的结果。

#### 请求参数 (JSON Body)

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `device_id` | string | 否 | 设备ID，留空使用默认设备 |
| `start_date` | string | 否 | 开始日期，格式 `YYYY-MM-DD` |
| `end_date` | string | 否 | 结束日期，格式 `YYYY-MM-DD` |
| `report_type` | string | 否 | 报告类型：`daily`（默认）/ `weekly` / `monthly` |

#### 请求示例

```json
{
  "device_id": "102000018415",
  "start_date": "2026-05-01",
  "end_date": "2026-05-08",
  "report_type": "weekly"
}
```

#### 响应格式

```json
{
  "code": 200,
  "msg": "报警分析完成",
  "data": {
    "statistics": {
      "total": 856276,
      "active": 26471,
      "by_device": [
        { "device_id": "102000000996", "device_name": "正2#衡远合膏机", "count": 801745 }
      ],
      "by_type": [
        { "point_id": "AlarmMix20", "count": 12570, "alarm_name": "进料超重" }
      ],
      "hourly_trend": [
        { "hour": 0, "count": 150 }
      ]
    },
    "analysis": {
      "total_anomalies": 26,
      "severity_distribution": {
        "严重": 12,
        "高": 0,
        "中": 10,
        "低": 4
      },
      "alarm_predictions": 3,
      "details": [
        {
          "时间": "2026-05-08T19:42:00",
          "参数": "过滤器压差",
          "当前值": 20.0,
          "异常类型": "越限",
          "严重程度": "严重",
          "描述": "过滤器压差低于报警下限"
        }
      ]
    },
    "query": {
      "device_id": "102000018415",
      "start_date": "2026-05-01",
      "end_date": "2026-05-08",
      "hours": 168
    },
    "report_type": "weekly",
    "report_date": "2026-05-01",
    "saved": true
  }
}
```

#### 响应字段说明

| 字段 | 说明 |
|------|------|
| `statistics.total` | 时间段内总报警记录数 |
| `statistics.active` | 活跃报警数（point_value=1） |
| `statistics.by_device` | 按设备统计 Top10 |
| `statistics.by_type` | 按报警类型统计 Top10（含中文名称） |
| `statistics.hourly_trend` | 按小时分布的报警趋势 |
| `analysis.total_anomalies` | AI 检测到的异常点总数 |
| `analysis.severity_distribution` | 严重程度分布（严重/高/中/低） |
| `analysis.alarm_predictions` | 报警预测数量 |
| `analysis.details` | 异常详情列表 |
| `query` | 查询参数回显 |

---

### 2. 查询报警记录

**`GET /api/alarms`**

分页查询报警记录，支持多种筛选条件。

#### 查询参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备ID |
| `keyword` | string | 报警名称搜索 |
| `start_date` | string | 开始日期 (YYYY-MM-DD) |
| `end_date` | string | 结束日期 (YYYY-MM-DD) |
| `only_active` | boolean | 只显示活跃报警 |
| `page` | int | 页码 (从1开始) |
| `page_size` | int | 每页数量 (1-200) |

---

### 3. 获取报警统计

**`GET /api/alarms/statistics`**

获取报警统计信息（纯 SQL 聚合，不包含 AI 分析）。

#### 查询参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 设备ID |
| `start_date` | string | 开始日期 |
| `end_date` | string | 结束日期 |

---

### 4. 获取报警设备列表

**`GET /api/alarms/devices`**

返回有报警记录的设备列表。

---

### 5. 获取报警类型定义

**`GET /api/alarms/types`**

返回报警类型定义（点位ID与中文名称映射）。

#### 查询参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `device_id` | string | 指定设备ID，留空返回全部 |

---

### 6. 查询报警分析历史

**`GET /api/alarms/analysis/history`**

按报告类型列出报警分析历史记录。

#### 查询参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `report_type` | string | 报告类型：`daily`/`weekly`/`monthly`，默认 `daily` |
| `limit` | int | 返回条数，默认 50 |

#### 响应示例

```json
{
  "code": 200,
  "data": [
    {
      "id": 1,
      "report_date": "2026-05-08",
      "device_id": "all",
      "total_alarms": 91203,
      "active_alarms": 26471,
      "total_anomalies": 1061,
      "severity": { "严重": 245, "高": 0, "中": 154, "低": 662 },
      "created_at": "2026-05-08T20:30:00",
      "updated_at": "2026-05-08T20:35:00"
    }
  ]
}
```

---

### 7. 获取报警分析详情

**`GET /api/alarms/analysis/detail`**

获取指定日期和类型的报警分析完整详情。

#### 查询参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `report_type` | string | 是 | 报告类型 |
| `report_date` | string | 是 | 报告日期 (YYYY-MM-DD) |
| `device_id` | string | 否 | 设备ID |

---

## 数据库表结构

分析结果存入三张表，通过 `UNIQUE(report_date, device_id)` 约束实现同日期覆盖：

| 表名 | 说明 |
|------|------|
| `alarm_analysis_daily` | 日报 |
| `alarm_analysis_weekly` | 周报 |
| `alarm_analysis_monthly` | 月报 |

每张表结构相同：

| 列名 | 类型 | 说明 |
|------|------|------|
| `id` | SERIAL | 主键 |
| `report_date` | DATE | 报告日期 |
| `device_id` | VARCHAR(50) | 设备ID |
| `statistics` | JSONB | SQL 统计结果 |
| `analysis` | JSONB | AI 分析结果 |
| `query_params` | JSONB | 查询参数 |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

---

## 设备 ID 参考

| 设备ID | 设备名称 |
|--------|----------|
| `102000018415` | 正1#金帆球磨机 |
| `102000000996` | 正2#衡远合膏机 |

## 异常类型说明

| 类型 | 说明 |
|------|------|
| `越限` | 参数值超出报警阈值 |
| `漂移` | 参数值偏离正常范围但未达报警阈值 |
| `突变` | 参数值短时间大幅变化 |
| `卡死` | 参数值长时间无变化 |

## 严重程度说明

| 等级 | 说明 |
|------|------|
| `严重` | 超出报警阈值，需立即处理 |
| `高` | 接近报警阈值或突变幅度大 |
| `中` | 偏离正常范围 |
| `低` | 轻微异常，可能数据卡死 |
