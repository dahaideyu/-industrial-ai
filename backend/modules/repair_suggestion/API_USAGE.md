# 超威知识库服务 API 使用说明

## 服务启动

```bash
# 方式1：直接运行
uv run python main.py

# 方式2：使用uvicorn
uv run uvicorn main:app --reload
```

服务默认地址：`http://localhost:8000`

API文档地址：`http://localhost:8000/docs`

---

## 接口1：获取维修建议

### 接口信息
- **URL**: `/api/repair-suggestion`
- **Method**: `POST`
- **Content-Type**: `application/json`

### 请求参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| device_name | string | 是 | 设备型号 |
| device_type | string | 是 | 设备类型 |
| fault_description | string | 是 | 故障现象描述 |

### 请求示例

```bash
curl -X POST "http://localhost:8000/api/repair-suggestion" \
  -H "Content-Type: application/json" \
  -d '{
    "device_name": "3#负连铸线",
    "device_type": "连铸机",
    "fault_description": "负连铸三号机超声波烘干机故障"
  }'
```

### 返回参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| status | string | 状态：success/error |
| conclusion | string | 故障处理总结（150-200字） |
| context | string | 返回的详细维修建议内容 |
| error_code | int | 错误码：0表示成功 |
| error_message | string | 错误信息 |

### 返回示例

#### 成功返回

```json
{
  "status": "success",
  "conclusion": "该故障可能由超声波烘干机线路问题或温度传感器异常引起。历史记录显示曾有类似故障通过线路处理修复。建议优先检查电源线路连接、温度传感器工作状态及控制面板错误代码，参照历史维修经验进行线路排查与处理，维修前确保断电并做好安全防护。",
  "context": "根据知识库记录，设备3#负连铸线曾出现与\"负连铸三号机超声波烘干机故障\"完全匹配的维修单。具体详情如下：\n\n- **工单编号**：WXGD20251020002\n- **报修时间**：2025-10-20 20:25:27\n- **维修完成时间**：2025-10-21 09:23:51\n- **故障性质**：紧急\n- **故障类型**：电器故障\n- **根本原因分析**：超声波温度不正常\n- **处理措施**：线路处理后正常 [ID:0]\n\n该记录显示，类似故障此前已发生并已通过线路处理修复。\n\n## 故障分析\n历史维修单中有类似故障记录（工单编号：WXGD20251020002），之前的问题原因是超声波温度不正常，处理方式为线路处理后正常。\n\n## 排查步骤\n1. 首先检查超声波烘干机的电源线路连接是否正常\n2. 检查温度传感器是否工作正常\n3. 检查烘干机的控制面板显示是否有错误代码\n\n## 解决方案\n参照历史维修记录，建议先检查并处理线路问题，如线路松动、接触不良等。\n\n## 注意事项\n- 维修前请确保设备已断电\n- 维修时请注意安全防护\n- 如问题无法解决，请联系专业技术人员",
  "error_code": 0,
  "error_message": ""
}
```

#### 失败返回

```json
{
  "status": "error",
  "conclusion": "",
  "context": "",
  "error_code": 1,
  "error_message": "LLM调用失败: 500"
}
```

---

## 接口2：维修单智能评分

### 接口信息
- **URL**: `/api/repair-order-scoring`
- **Method**: `POST`
- **Content-Type**: `application/json`

### 请求参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| is_have_pic | boolean | 是 | 是否有图片 |
| is_have_video | boolean | 是 | 是否有视频 |
| handleAnalysis | string | 是 | 根因分析 |
| handleAction | string | 是 | 处理措施 |
| is_replace_spare | boolean | 是 | 是否更换备件 |
| is_have_spare_record | boolean | 是 | 是否有备件更换记录 |

### 请求示例

```bash
curl -X POST "http://localhost:8000/api/repair-order-scoring" \
  -H "Content-Type: application/json" \
  -d '{
    "is_have_pic": true,
    "is_have_video": false,
    "handleAnalysis": "检查发现是超声波温度不正常导致的故障，排查过程中检测了温度传感器和线路连接",
    "handleAction": "已重新连接线路并进行测试，设备工作正常，建议定期检查线路连接",
    "is_replace_spare": false,
    "is_have_spare_record": false
  }'
```

### 返回参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| score | float | 评分：0-5，支持0.5分步进 |
| explanation | string | 评分说明 |

### 返回示例

```json
{
  "score": 4.5,
  "explanation": "总分：4.5 🌟🌟🌟🌟✨\n\n评分详情：\n  • 已上传图片，+1星 🌟\n  • 未上传视频，扣1星\n  • 内容质量：根因分析详细描述了故障来源和排查过程，处理措施提供了解决步骤并带有预防建议 (+2.5星)\n  • 本维修单未更换备件\n\n太棒了！这份维修单写得非常优秀，堪称范本！🎉"
}
```

---

## 接口5：健康检查

### 接口信息
- **URL**: `/health`
- **Method**: `GET`

### 请求示例

```bash
curl "http://localhost:8000/health"
```

### 返回示例

```json
{
  "status": "ok"
}
```

---

## 评分规则说明

### 满分5星，评分组成：

1. **图片**（1星）
   - 已上传：+1星
   - 未上传：扣1星

2. **视频**（1星）
   - 已上传：+1星
   - 未上传：扣1星

3. **内容质量评分**（1-3星）
   - 更换备件：满分2星
   - 不更换备件：满分3星
   - 根据根因分析和处理措施的详细程度评分

4. **备件记录**（1星，仅更换备件时检查）
   - 有记录：+1星
   - 无记录：扣1星

---

---

## 接口3：获取精益改善任务建议

### 接口信息
- **URL**: `/api/task-suggestion`
- **Method**: `POST`
- **Content-Type**: `application/json`

### 请求参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| procedure | string | 是 | 工序 |
| task_type | string | 是 | 任务分类 |
| task_description | string | 是 | 任务描述 |

### 请求示例

```bash
curl -X POST "http://localhost:8000/api/task-suggestion" \
  -H "Content-Type: application/json" \
  -d '{
    "procedure": "表干",
    "task_type": "质量改善",
    "task_description": "表干铅膏水分不合格8.45"
  }'
```

### 返回参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| status | string | 状态：success/error |
| conclusion | string | 任务建议总结（150-200字） |
| context | string | 返回的完整任务建议内容 |
| error_code | int | 错误码：0表示成功 |
| error_message | string | 错误信息 |

### 返回示例

#### 成功返回（有知识库内容）

```json
{
  "status": "success",
  "conclusion": "表干铅膏水分不合格8.45，超出标准范围，需从窑温控制和铅膏配比两方面入手。建议优先调整表干窑温度曲线，同时核查铅膏搅拌工艺参数，确保水分达标。加强过程抽检频次，防止批量不良。",
  "context": "## 问题分析\n\n根据知识库记录，曾有类似\"表干铅膏水分偏高\"的改善案例，通过降低表干窑温度和调整搅拌时间得到解决。\n\n从精益生产角度分析，该问题反映了过程控制能力的不足，根本原因可能包括：\n1. 窑温曲线偏离标准工艺窗口\n2. 铅膏搅拌时间或配比波动\n3. 来料水分含量不一致\n\n## 改善措施\n\n**短期对策：**\n- 立即调整表干窑各段温度，降低5-10℃进行验证\n- 加强出窑产品水分抽检，每批次至少3个样本\n\n**长期预防：**\n- 建立窑温SPC控制图，设置预警上下限\n- 标准化铅膏搅拌作业指导书，明确搅拌时间和速度\n\n## 预期效果\n\n- 铅膏水分合格率提升至98%以上\n- 减少返工和报废损失\n\n## 注意事项\n\n- 调温幅度不宜过大，防止铅膏过干导致开裂\n- 需记录每次调温后的水分数据，便于追溯",
  "error_code": 0,
  "error_message": ""
}
```

#### 成功返回（无知识库内容）

```json
{
  "status": "success",
  "conclusion": "表干铅膏水分不合格涉及窑温控制与铅膏工艺参数管理，建议从温度曲线优化、搅拌工艺标准化及来料检验三方面入手，建立过程监控机制，持续改善水分合格率。",
  "context": "知识库中未检索到相关内容，以下是行业通用改善建议：\n\n## 问题分析\n\n表干铅膏水分不合格通常与烘干温度、烘干时间、铅膏配方及环境湿度有关...\n\n## 改善措施\n\n...\n\n## 预期效果\n\n...\n\n## 注意事项\n\n...",
  "error_code": 0,
  "error_message": ""
}
```

#### 失败返回

```json
{
  "status": "error",
  "conclusion": "",
  "context": "",
  "error_code": 1,
  "error_message": "LLM调用失败: 500"
}
```

---

## 接口4：精益改善任务智能评分

### 接口信息
- **URL**: `/api/task-scoring`
- **Method**: `POST`
- **Content-Type**: `application/json`

### 请求参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| plan_end_time | string | 是 | 期望完成日期（格式：YYYY-MM-DD） |
| close_time | string | 是 | 关闭日期（格式：YYYY-MM-DD） |
| task_description | string | 是 | 任务问题描述 |
| handle_action | string | 是 | 处理措施 |
| is_upload_file | boolean | 是 | 是否上传文件 |

### 请求示例

```bash
curl -X POST "http://localhost:8000/api/task-scoring" \
  -H "Content-Type: application/json" \
  -d '{
    "plan_end_time": "2026-05-20",
    "close_time": "2026-05-18",
    "task_description": "表干铅膏水分不合格8.45",
    "handle_action": "不沾板情况下降低表干窑温度",
    "is_upload_file": true
  }'
```

### 返回参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| score | float | 评分：0-5，支持0.5分步进 |
| explanation | string | 评分说明 |

### 返回示例

```json
{
  "score": 4.5,
  "explanation": "总分：4.5 🌟🌟🌟🌟✨\n\n评分详情：\n  • 未延期，+1星 🌟\n  • 已上传文件，+1星 🌟\n  • 内容质量：任务描述清晰包含具体指标（水分8.45），处理措施针对性强，逻辑自洽 (+2.5星)\n\n太棒了！这份精益改善任务完成得非常出色，堪称范本！🎉"
}
```

---

## 评分规则说明

### 维修单评分（接口2）

满分5星，评分组成：

1. **图片**（1星）
   - 已上传：+1星
   - 未上传：扣1星

2. **视频**（1星）
   - 已上传：+1星
   - 未上传：扣1星

3. **内容质量评分**（1-3星）
   - 更换备件：满分2星
   - 不更换备件：满分3星
   - 根据根因分析和处理措施的详细程度评分

4. **备件记录**（1星，仅更换备件时检查）
   - 有记录：+1星
   - 无记录：扣1星

### 任务评分（接口4）

满分5星，评分组成：

1. **是否延期**（1星）
   - 未延期（close_time ≤ plan_end_time）：+1星
   - 已延期（close_time > plan_end_time）：扣1星

2. **是否上传文件**（1星）
   - 已上传：+1星
   - 未上传：扣1星

3. **处理措施质量**（1-3星）
   - 任务描述（40%权重）：评估问题描述的清晰度、是否有量化指标
   - 处理措施（60%权重）：评估措施的详细程度、逻辑自洽性、是否针对问题根因
   - 特别关注"自洽性"：处理措施是否真正针对任务描述中的问题

---

## 日志说明

- 日志目录：`./logs/`
- 日志文件：`app.log`（每小时自动分割）
- 日志保留：7天
- 日志级别：DEBUG（详细记录所有请求和响应）
