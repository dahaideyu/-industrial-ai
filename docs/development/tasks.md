# 前后端分离重构任务清单

## 目标
将当前单体 Flask 应用重构为前后端分离架构：
- **frontend/**: Vue 3 + Vite + Tailwind CSS 前端项目
- **backend/**: Flask 纯 API 后端服务
- **docs/**: 项目文档

## 任务列表

### Task 1: 目录重构 — 迁移后端代码到 backend/
- [x] 创建 backend/、frontend/、docs/ 目录
- [x] 将 src/app.py 移动到 backend/app.py
- [x] 将 ai_analysis/ 移动到 backend/ai_analysis/
- [x] 将 prompts/ 移动到 backend/prompts/
- [x] 将 src/lean.json 移动到 backend/lean.json
- [x] 将 requirements.txt 复制到 backend/requirements.txt
- [x] 将文档（README.md、DEPLOYMENT.md、CLAUDE.md）移动到 docs/
- [x] 更新 backend/app.py 中的导入路径
- [x] 验证后端能独立启动

### Task 2: 后端纯 API 化 + CORS
- [x] 删除 backend/app.py 中所有页面路由（/, /dashboard, /report, /analysis, /jobs）
- [x] 删除 render_template 和 redirect 导入
- [x] 删除 templates/ 和 static/ 文件夹引用
- [x] 安装 flask-cors
- [x] 添加 CORS 配置
- [x] 添加 /api/health 健康检查端点
- [x] 将 API 路由拆分为 FastAPI APIRouter（backend/routes/）
- [x] 验证所有 /api/* 端点返回 JSON

### Task 3: 前端项目初始化（Vite + Vue 3）
- [x] 初始化 Vite + Vue 3 项目
- [x] 安装 Tailwind CSS
- [x] 配置 tailwind.config.js
- [x] 配置 vite.config.js 代理到后端
- [x] 验证前端能运行

### Task 4: Dashboard 页面实现
- [x] 创建 API 客户端封装
- [x] 创建 Dashboard.vue
- [x] 实现数据加载逻辑
- [x] 配置路由
- [x] 联调数据

### Task 5: Report + Analysis + Jobs 页面
- [x] 创建 Report.vue（模板选择 + JSON 输入 + SSE 流式输出）
- [x] 创建 Analysis.vue（模块卡片 + 参数配置 + 结果展示）
- [x] 创建 Jobs.vue（统计卡片 + 筛选 + 表格 + 自动刷新）
- [x] 创建 App.vue 导航布局
- [x] 配置所有路由

### Task 6: 联调部署
- [x] 完整联调前后端
- [x] 更新 ecosystem.config.js
- [x] 更新 docs/DEPLOYMENT.md
- [x] 更新 docs/README.md
- [x] 清理废弃文件（src/、templates/、static/、design/）

---

## Phase 2: 设备特征工程 + 预测性维护数据管道

### Task 7: 数据库连接层打通（MySQL/PostgreSQL via cntlm）
- [x] 分析企业代理限制（cntlm NTLM 认证，端口白名单）
- [x] 发现 MySQL 23306 端口被代理拦截，改用 TimescaleDB 5432 端口
- [x] 修复 cntlm.ini 无效代理问题，生成 `D:\tools\Cntlm\cntlm_bosch.ini`（SSPI 自动认证）
- [x] 修复 SSL 在 HTTP CONNECT 隧道中不稳定问题（sslmode=disable + keepalives）
- [x] 安装 Python 3.14 兼容包：psycopg2-binary, pandas, numpy, pyarrow

### Task 8: MySQL Schema 探查
- [x] 创建 `backend/tools/explore_mysql_schema.py`（备用，连 MySQL 用）
- [x] 探查 TimescaleDB 表结构：11 台设备，24+ 周 chunks，数据从 2025-10 到 2026-04
- [x] 确认 `dev_device_param_detail_record` 为主时序表（55 参数/设备）
- [x] 确认关键参数：合膏温度、加酸温度×6、酸混真空度×6、加水/铅粉/加酸重量等
- [x] 建立查询策略：按天批量查询（约 116K 行/天，8~80s），避免 COUNT(*)

### Task 9: 设备特征提取 Pipeline（已完成验证）
- [x] 创建 `backend/tools/extract_device_features.py`
- [x] Step 1: 按天批量抽取原始参数 + 状态事件
- [x] Step 2: Pivot → 宽表（5分钟重采样，55 列）
- [x] Step 3: 滑动窗口统计（×4窗口 ×4统计 = +220列）
- [x] Step 4: 变化率特征（diff/dt = +55列）
- [x] Step 5: 多参数交互特征（自动高相关对，ratio+delta = +40列）
- [x] Step 6: 告警/状态计数特征（= +11列）
- [x] 验证结果：864行 × **986列** 特征矩阵，已保存 `features_102000000996_3d.parquet`

### Task 10: 全量特征提取（已完成 ✅ — 2026-05-23）
- [x] 创建输出目录 `features_output/`
- [x] 直接连接 TimescaleDB（无需 cntlm，通过 backend/.env 配置）
- [x] 11 台设备 × 30 天全量提取 → 12 个 parquet（~79MB）
- [x] 和膏机：~8,000 行 × 986~1004 列，球磨机：8,341 行 × 238 列

### Task 11: 标签生成 + 模型训练（已完成 ✅ — 2026-05-23）
- [x] 定义故障标签：基于 `dev_device_status_record` 中 status=2（报警）
- [x] 生成预测目标：未来 15 分钟内是否发生报警（二分类）
- [x] 训练模型：XGBoost / 随机森林
- [x] 评估：合并模型 AUC-ROC 0.999, Recall 0.781, Precision 0.610
- [x] 集成到 `backend/modules/maintenance_report/` API
  - 新增 `POST /api/maintenance-reports/predict` — 设备故障预测端点
  - 新增 `GET /api/maintenance-reports/predict/model-info` — 模型信息端点
  - 支持 LLM 解释预测结果（explain_with_llm=true）
  - 模型文件: `features_output/models/combined/fault_predictor_best.pkl`

---

## Phase 3: 实施路径与进度跟踪

### 一、总体思路

| 项目 | 状态 |
|------|------|
| 异常波动预警（无监督）| ✅ IQR动态阈值 + 孤立森林 + 健康指数 |
| 故障预测（有监督）| ✅ XGBoost AUC 0.999, Recall 0.78 |

### 二、数据整合与预处理

| 项目 | 状态 | 待完成 |
|------|------|--------|
| 时间对齐（参数左连接告警）| ✅ `/aligned-data` 端点 | |
| 衍生列：is_alarm + alarm_count_Nmin | ✅ | |
| 缺失值处理（短时插值）| ⚠️ 特征工程做了 interpolate(limit=3) | [ ] 长时缺失标记（gap > N分钟标记为数据中断）|
| 区分运行/停机 | ⚠️ 异常检测训练过滤了运行时段 | [ ] 系统化：基于电流/转速自动判停 |
| 故障标签记录 | ⚠️ 从 status_record 取 status=2 | [ ] 补充人工确认的故障时间点 |

### 三、异常波动预警

| 项目 | 状态 | 待完成 |
|------|------|--------|
| 单参数动态阈值（IQR）| ✅ | |
| EWMA + 3σ | ⬜ | [ ] 实现 EWMA 控制线 |
| 多参数联合异常检测（孤立森林）| ✅ | |
| PCA + Hotelling T²/Q统计量 | ⬜ | [ ] 实现 PCA 分解 + 统计量 |
| 自编码器 | ⬜ | [ ] 实现 Autoencoder 异常检测 |
| 融合告警的复合规则 | ✅ 告警惩罚分计入健康指数 | [ ] 细化规则："参数X超限 AND 告警Y" |
| 健康指数曲线 | ✅ 前端紫色曲线 | |

### 四、故障预测（2026-05-27 样本构造重构完成 ✅）

| 项目 | 状态 | 待完成 |
|------|------|--------|
| 预测目标：未来T小时是否故障 | ✅ 支持 1h / 2h / 4h 多窗口,各训独立模型 | |
| 正样本构造（故障前窗口）| ✅ purge=15min,故障前瞬态样本进 drop_mask 不参与训练 | |
| 负样本构造（稳定运行随机截取）| ✅ | |
| XGBoost / RandomForest 建模 | ✅ | |
| 按时间序列划分训练/测试 | ✅ 80/20 时序切分 + 60min embargo 防泄漏;train/test 均值分别拟合 | |
| 故障概率曲线 | ✅ | |
| SHAP 模型解释 | ✅ | |
| 生存分析/剩余寿命 | ⬜ | [ ] 探索 RUL 预测 |

**新方法首次评估 (2026-05-27, 10 台和膏机合并训练, 30 天数据 70,455 行):**

| 窗口 | Best | AUC-ROC | Precision | Recall | F1 | 训练正例率 |
|------|------|---------|-----------|--------|------|----------|
| 60 min  | RandomForest | 0.743 | 0.000 | 0.000 | 0.000 | 0.64% |
| 120 min | RandomForest | **0.819** | 0.039 | 0.224 | 0.067 | 1.41% |
| 240 min | RandomForest | 0.783 | 0.090 | **0.413** | 0.148 | 2.81% |

> 对比旧方法 (stratify split + 无 purge + 单 15min 窗口): AUC 0.999 / R 0.781 / P 0.610。
> 新方法 AUC 大幅下降是**预期且健康**的 — 旧高分主要来自 stratify split 造成的数据泄漏。
> 当前真实泛化性能 AUC 0.74-0.82 才是有意义的基线。

**遗留问题:**
- 60min 窗口 F1=0 — 0.5 阈值过高,模型一个正预测都没出,需要阈值调优 (例如基于 PR 曲线寻找最佳阈值)
- 120min 窗口是 AUC sweet spot 但 Precision 偏低 (0.039),误报率高
- 设备 102000018794 在 30 天窗口内 0 告警样本 → 该设备未参与正例信号贡献
- 球磨机 102000018415 (11 参数) 因 raw_params<20 被跳过,需单独建模
- 推理端 fault_predictor.py 仍加载老路径单一模型,需要支持 `?window=60|120|240`

### 五、质量异常预测

| 项目 | 状态 | 待完成 |
|------|------|--------|
| 全部 | ⬜ 无质量检测数据 | [ ] 对接质量检测系统 |

### 六、持续优化

| 项目 | 状态 | 待完成 |
|------|------|--------|
| 人工反馈闭环 | ⬜ | [ ] 收集预警确认→新标签→持续训练 |
| 球磨机单独建模 | ⬜ | [ ] 238列特征，参数体系与和膏机不同 |

---

## 下次开工优先做

1. ~~故障预测样本构造修复~~ — **2026-05-27 完成** (commit `331bff8`)
   - ✅ 时序 80/20 + 60min embargo + 训练拟合均值
   - ✅ purge 15min 瞬态丢弃
   - ✅ 多窗口 60/120/240min 各独立模型 → `features_output/models/combined/{w}min/`
2. **[ ] 故障预测阈值调优** (新增,接续上一步):
   - 60min 窗口默认 0.5 阈值下 F1=0,需基于 PR 曲线找最佳阈值
   - 输出每个窗口的 threshold/precision/recall 曲线
3. **[ ] 推理端 API 支持多窗口** (新增):
   - `FaultPredictor` 类加载 3 个模型,`predict?window=60|120|240` 选模型
   - 默认窗口决策依据:120min AUC 最高
4. **[ ] EWMA + 3σ 动态阈值**(补全异常检测方法)
5. **[ ] PCA 分解 + Hotelling T²/Q 统计量**(区分变量关系失衡 vs 单变量超限)
6. **[ ] 缺失值长时标记**(数据中断检测)
7. **[ ] 球磨机 102000018415 单独建模**(11 参数被合并模型跳过)

---

## 关键原则
1. 每步一个 commit
2. 先让后端能跑（Task 1-2 完成后后端必须独立运行）
3. 先让前端能跑（Task 3 完成后 dev server 必须能启动）
4. 渐进式页面实现
5. 不引入复杂依赖（不用 Pinia/Vuex，不用 UI 组件库）

## 运行方式

**后端：**
```bash
# 创建虚拟环境（首次）
cd backend
python -m venv venv

# 激活虚拟环境（Windows）
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 运行
set PROVIDER=deepseek
python app.py
# 服务运行在 http://localhost:9300
```

**前端：**
```bash
cd frontend
npm install
npm run dev
# 服务运行在 http://localhost:5173
```
