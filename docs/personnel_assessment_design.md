# 人员考核报告 - 设计方案

## Context

基于两个现有 API 接口的数据生成**人员考核报告**。每个工序有两位负责人（当前数据中为"A班"/"B班"，后续替换为具体姓名）。

核心设计原则：
- **工序内归一化计分**：不同工序基准不同，不做跨工序绝对值对比
- **不作预处理聚合**：原始数据直接注入 prompt，由 LLM 按评分规则自行分析
- **动态名称**：负责人名称从数据中读取，不硬编码

两个数据源：
- **接口1** — 运转率 (`/device/overview/runningRate`)：`classRate`、`numerator`、`denominator`
- **接口2** — 质量 (`/quality/inspection/record/overview/quality`)：`onceQualifiedRate`、`passRatePercent`、`unQualifiedCount`

---

## 评分标准（写入 Prompt 模板）

### 一、评分维度与权重

| 维度 | 满分 | 核心指标 |
|------|------|---------|
| 运转率 | 50 分 | `classRate` |
| 质量 | 50 分 | `onceQualifiedRate`（一次合格率） |
| **合计** | **100 分** | |

### 二、工序内计分规则（归一化）

```
运转率得分 = 50 × (本人运转率 ÷ 工序内较高者运转率)
质量得分   = 50 × (本人一次合格率 ÷ 工序内较高者一次合格率)
工序得分   = 运转率得分 + 质量得分
```

**示例**（正冲网，A班 81.9%, B班 80.8%）：

| | 运转率 | 运转率得分 | 一次合格率 | 质量得分 | 工序得分 |
|---|--------|----------|-----------|---------|---------|
| A班 | 81.9% | 50.0 | 96.82% | 50.0 | 100.0 |
| B班 | 80.8% | 49.3 | 89.63% | 46.3 | 95.6 |

### 三、综合得分

```
综合得分 = 所有参与工序得分的算术平均值
```

### 四、优胜方面（不计数，只列举）

对每个负责人，列出在哪些工序上表现更优：

- **运转率优于对方**：列举工序名称
- **质量优于对方**：列举工序名称
- **双优工序**：运转率和质量都优于对方的工序

### 五、等级评定

| 综合得分 | 等级 | 含义 |
|---------|------|------|
| ≥ 95 | **S** | 全面优胜 |
| 90 ~ 94.9 | **A** | 表现优秀 |
| 80 ~ 89.9 | **B** | 表现良好 |
| 70 ~ 79.9 | **C** | 有待提升 |
| < 70 | **D** | 需重点关注 |

---

## 模块架构

```
backend/modules/personnel_assessment/
├── __init__.py
├── routes.py
├── worker.py              # 编排器（拉参 → 注入 prompt → LLM 生成）
├── prompts/
│   ├── __init__.py
│   ├── loader.py
│   └── personnel_assessment_report.txt   # 包含评分规则 + 报告结构的完整 prompt
```

> 与现有模块（`quality_overview`、`lean_morning_daily`）结构一致。
> 不做 `scorer.py`，评分规则直接写在 prompt 模板中，LLM 按规则自行计算。

---

## 数据流

```
输入：runningRateData + qualityData（原始 JSON）

  ├─ worker 将两个原始数据合并为一个 payload
  ├─ 通过 {data_sources} 占位符注入 prompt 模板
  ├─ prompt 中已写明评分规则 + 报告结构要求
  └─ LLM 生成完整报告

不做任何 Python 层预处理，LLM 完全按 prompt 中的规则自行分析。
```

---

## Prompt 模板结构

```
## 角色设定
你是一名生产管理考核专家。请根据以下运转率和质量数据，
对每个工序的两位负责人进行对比分析并生成人员考核报告。

## 数据说明
- 运转率数据 (runningRateData)：各工序整体运转率 + 按负责人(children)拆分的运转率
  字段：classRate（运转率）、chainRate（环比）、numerator/denominator
- 质量数据 (qualityData)：各工序检验结果 + 按负责人(classDataList)拆分的合格率
  字段：onceQualifiedRate（一次合格率）、passRatePercent（合格率）、unQualifiedCount

## 评分规则
（此处写入评分标准章节的完整内容）

## 报告结构要求
（此处写入报告结构，含5个章节的具体要求）

## 行为约定
- 负责人名称从数据中动态读取，不要改为"A班/B班"
- 禁止出现任何数字ID
- 百分比保留一位小数
- 不做跨工序绝对值对比
- 严格遵守上述评分规则

## 原始数据
{runningRateData}
{qualityData}
```

---

## 报告输出结构

```
## 人员考核周报

### 📌 结论
- 报告周期 + 考核工序数
- 两人综合得分 + 等级
- 关键结论（差距最大的工序 + 整体表现对比）

### 一、综合评分总览
- 综合得分表 + 等级
- 优胜方面对比（运转率/质量各自优于对方的工序列表）
- 运转率最大差距 TOP 3
- 质量最大差距 TOP 3

### 二、运转率分析
- 各工序运转率对比表（按差值降序排列）

### 三、质量分析
- 各工序合格率对比表（按一次合格率差值降序排列）
- 检验维度明细（首检/自检/抽检/送检）

### 四、评分明细
- 各工序评分明细表（得分+总分）
- 标注双优工序

### 五、改进建议
- 针对落后方给出具体改进方向
```

---

## API 接口

```python
POST /api/personnel_assessment
{
    "runningRateData": {...},   # 接口1 完整响应
    "qualityData": {...},       # 接口2 完整响应
    "reportDate": "2026-05-24",
    "period": "week"
}
```

---

## 关键文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/modules/personnel_assessment/__init__.py` | 新建 | |
| `backend/modules/personnel_assessment/routes.py` | 新建 | API 路由 |
| `backend/modules/personnel_assessment/worker.py` | 新建 | 编排器 |
| `backend/modules/personnel_assessment/prompts/__init__.py` | 新建 | |
| `backend/modules/personnel_assessment/prompts/loader.py` | 新建 | 模板加载 |
| `backend/modules/personnel_assessment/prompts/personnel_assessment_report.txt` | 新建 | Prompt 模板（含评分规则） |
| `config/report_templates.yaml` | 修改 | 新增 personnelAssessmentReport 配置 |

---

## 实施顺序

1. 新建模块目录结构
2. 编写 `personnel_assessment_report.txt`（Prompt 模板，含评分规则 + 报告结构）
3. 实现 `worker.py`（原始数据拼装 → LLM 调用）
4. 实现 `routes.py`
5. 配置 `report_templates.yaml`
6. 用 `data/debug_section_prompt.txt` 端到端验证

## 验证方式

用 `data/debug_section_prompt.txt` 中的真实数据触发报告生成，检查：
1. LLM 是否正确识别了两个负责人名称
2. 评分计算是否正确（对照手工计算结果）
3. 报告结构是否完整
