# 设备特征工程 Pipeline 文档

**日期：** 2026-05-22  
**作者：** Claude Code + slu5szh  
**状态：** 已验证，可生产运行

---

## 一、背景与目标

超威工厂部署了 11 台工艺设备（和膏机 × 10 + 球磨机 × 1），通过 IoT 网关每 5 秒至 5 分钟采集一次参数，存入 MySQL（现场内网）并同步到远端 TimescaleDB（PostgreSQL）。

**目标：** 将原始时序参数 + 告警事件拼成"设备完整状态向量"，供预测性维护模型训练使用。

核心思路：
> 原始参数（60列）→ 宽表 → 滑动窗口统计 + 多参数交互 + 告警计数 → 980+ 列  
> 每一行 = "该时刻设备的完整状态向量" → 喂给模型学习"什么状态会导致故障"

---

## 二、网络访问架构

### 企业代理限制

| 连接方式 | 状态 | 说明 |
|---------|------|------|
| MySQL 127.0.0.1:13306 → CHANGE_ME:23306 | ❌ 被拦截 | 企业代理不允许 CONNECT 到 23306 |
| PostgreSQL 127.0.0.1:15432 → CHANGE_ME:5432 | ✅ 正常 | 5432 端口被代理白名单放行 |
| HTTP/HTTPS (pip install 等) | ✅ 正常 | 走 NTLM 代理 |

### cntlm 配置

原始 `cntlm.ini` 有两个失效代理（10.0.0.41:8080, 10.0.0.42:8080），已生成最小配置文件：

**`D:\tools\Cntlm\cntlm_bosch.ini`**
```ini
Username    slu5szh
Domain      APAC
Proxy       10.8.136.209:3128
NoProxy     localhost, 127.0.0.*, 10.*, 192.168.*
Listen      3128
Auth        NTLMv2
SSPI        NTLM          # 自动使用 Windows 域凭据，无需手动输密码
Tunnel      13306:CHANGE_ME:23306
Tunnel      15432:CHANGE_ME:5432
```

**启动命令（无需输密码）：**
```cmd
cntlm.exe -f -v -c D:\tools\Cntlm\cntlm_bosch.ini
```

### PostgreSQL 连接参数

```python
psycopg2.connect(
    host="127.0.0.1", port=15432,
    user="postgres", password="CHANGE_ME",
    sslmode="disable",      # SSL 在 HTTP CONNECT 隧道中不稳定
    keepalives=1,           # TCP keepalive 防止代理 idle timeout 断连
    keepalives_idle=30,     # 30s 无数据后发 keepalive
    keepalives_interval=10,
    keepalives_count=5,
    # 注意: 不设 statement_timeout，服务端默认无限制
)
```

> **为什么 sslmode=disable？**  
> cntlm 用 HTTP CONNECT 方法建立 TCP 隧道，企业代理会对隧道中的流量做 DPI。  
> SSL 握手流量触发代理的 SSL 检查，导致连接在第一次查询时报 "SSL error: unexpected eof"。  
> 关闭 SSL 后，明文 SQL 流量通过代理不受干扰。

---

## 三、数据库结构

### 设备列表（11 台）

| device_id（编码） | device_name | numeric_id |
|----------------|-------------|------------|
| 102000000995 | 正1#和膏机 | 17 |
| 102000000996 | 正2#衡远合膏机 | 18 |
| 102000018278 | 正3#和膏机 | 19 |
| 102000018279 | 正4#和膏机 | 20 |
| 102000018796 | 正5#和膏机 | 21 |
| 102000018797 | 负1#和膏机 | 22 |
| 102000018798 | 负2#和膏机 | 23 |
| 102000018793 | 负3#和膏机 | 24 |
| 102000018794 | 负4#和膏机 | 25 |
| 102000018795 | 负5#和膏机 | 26 |
| 102000018415 | 正1#金帆球磨机 | 27 |

### 关键表

| 表名 | 类型 | 说明 | 数据量 |
|------|------|------|--------|
| `dev_device_param_detail_record` | TimescaleDB hypertable | 原始时序参数 | 2025-10 ~ 2026-04，24+ 周 chunks |
| `dev_device_status_record` | TimescaleDB hypertable | 设备状态事件 | 同期 |
| `dev_device_param` | 普通表 | 参数定义（含中文名/单位） | 1,269 行 |
| `device_info` | 普通表 | 设备信息 | 11 行 |

> **注意：** device_info.device_id 是字符串编码（'102000000996'），  
> device_info.id 是整数（18），dev_device_status_record.device_id 关联的是整数 id。

### 和膏机参数（以 102000000996 为例，55 个参数）

| 参数前缀 | 含义 | 采集频率 |
|---------|------|---------|
| `Tec_Hg_tep` | 合膏温度 | 5秒 |
| `Tec_DQD_DH` | 当前段号 | 5秒 |
| `Tec_Sszkd` | 速度 | 5秒 |
| `Tec_Water_Real_weight` | 加水实际重量 | 5秒 |
| `Tec_lead_Real_weight` | 铅粉实际重量 | 5秒 |
| `Tec_sour_Real_weight` | 加酸实际重量 | 5秒 |
| `Tec_Js1_tep ~ Tec_Js6_tep` | 加酸1~6温度 | 5分钟 |
| `Tec_Sh1_tep ~ Tec_Sh6_tep` | 酸混1~6温度 | 5分钟 |
| `Tec_Hs1_Vacuum ~ Tec_Hs6_Vacuum` | 酸混1~6真空度 | 5分钟 |
| `Tec_Jsbl_1 ~ Tec_Jsbl_6` | 加酸比例1~6 | 5分钟 |
| `Sta_Gtjc` 等 | 状态监控 | 5分钟 |

**数据量：** 约 116,000 行/天/设备（热缓存约 8s，冷缓存首次 80~240s）

---

## 四、特征工程 Pipeline

### 脚本位置

```
backend/tools/extract_device_features.py
```

### Pipeline 流程

```
原始数据 (长表)
  │  device_code | p_name | p_value | gather_time
  │
  ▼ Step 1: 按天抽取 (116K行/天, ~8s)
  │
  ▼ Step 2: Pivot + 5min重采样 → 宽表
  │  288行/天 × 55列
  │
  ▼ Step 3: 滑动窗口统计 (4窗口 × 4统计)
  │  + 55×4×4 = 880列  →  总计 935列
  │
  ▼ Step 4: 变化率 (diff/dt)
  │  + 55列  →  总计 990列
  │
  ▼ Step 5: 多参数交互 (自动选高相关对×2算子)
  │  + 40列  →  总计 1030列
  │
  ▼ Step 6: 告警/状态计数 (4时间窗口)
  │  + 11列  →  总计 ~1041列
  │
  ▼ 清理全空列
  └→ 最终: 864行 × 986列  (3天)
          8640行 × ~986列 (30天)
```

### 特征列分类（验证结果，3天，设备 102000000996）

| 类别 | 列数 | 举例 |
|------|------|------|
| 原始参数 | 55 | `Tec_Hg_tep`, `Tec_lead_Real_weight` |
| 滑动窗口均值 | 220 | `Tec_Hg_tep__5min_mean`, `Tec_Sszkd__30min_mean` |
| 滑动窗口标准差 | 220 | `Tec_Hg_tep__15min_std` |
| 滑动窗口最大/最小值 | 220+220 | `Tec_Hg_tep__60min_max` |
| 变化率 | 55 | `Tec_Hg_tep__diff_per_min` |
| 交互特征 | 40 | `iact__Tec_Hg_tep_div_Tec_Sszkd` |
| 告警/状态 | 11 | `alarm_cnt_15min`, `current_status_sec`, `min_since_last_alarm` |
| **合计** | **986** | — |

### 运行命令

```powershell
# 环境准备（首次）
pip install psycopg2-binary pandas numpy pyarrow --proxy http://127.0.0.1:3128

# 列出设备
python backend\tools\extract_device_features.py

# 单设备 3 天（验证用）
python backend\tools\extract_device_features.py `
    --device_code 102000000996 --days 3 `
    --out features_102000000996_3d.parquet

# 单设备 30 天
python backend\tools\extract_device_features.py `
    --device_code 102000000996 --days 30 `
    --out features_102000000996_30d.parquet

# 所有设备 7 天（约 1-2 小时）
python backend\tools\extract_device_features.py --all_devices --days 7
```

---

## 五、查询性能经验

| 查询类型 | 耗时 | 说明 |
|---------|------|------|
| 1 小时数据（4,849 行） | 3.3s | 热缓存 |
| 1 天数据（116K 行） | 8~80s | 热/冷缓存差异大 |
| 7 天数据（~814K 行） | 估 60~600s | 批量按天执行 |
| `COUNT(*)` on hypertable | >5 分钟后断连 | 代理 idle timeout，禁止使用 |
| `DISTINCT` 无时间范围 | 超时 | 需加 WHERE gather_time 限制到具体 chunk |

**性能优化原则：**
1. 永远加 `WHERE device_code = ? AND gather_time >= ? AND gather_time < ?`（两个条件都要）
2. 不要用 `COUNT(*)`，用 `pg_class.reltuples` 估算
3. 不要无范围 `DISTINCT`，限制到单个 chunk（7天区间）内
4. 用 `dev_device_param`（小表）查参数定义，不要扫 hypertable

---

## 六、下一步：标签生成 + 模型训练

### 标签定义

```sql
-- 故障标签: 未来 30 分钟内出现 status IN (2,3,4,5) 的状态事件
SELECT
    feature_time,
    CASE WHEN EXISTS (
        SELECT 1 FROM dev_device_status_record
        WHERE device_id = :numeric_id
          AND status IN (2, 3, 4, 5)
          AND start_time BETWEEN feature_time AND feature_time + INTERVAL '30 minutes'
    ) THEN 1 ELSE 0 END AS label_fault_30min
FROM feature_timestamps
```

### 推荐模型

| 场景 | 推荐模型 | 理由 |
|------|---------|------|
| 快速验证 | XGBoost / LightGBM | 986列高维稀疏特征，树模型天然适合 |
| 序列模式 | LSTM (滑动窗口输入) | 若要捕捉时序依赖关系 |
| 可解释性 | Random Forest + SHAP | 告知"哪个参数贡献最大" |

### 集成目标

将训练好的模型集成到 `backend/modules/maintenance_report/services/` 中，  
实现实时推理：当前时刻的特征向量 → 未来故障概率 → 触发维修建议 API。

---

## 七、相关文件

| 文件 | 说明 |
|------|------|
| `backend/tools/extract_device_features.py` | 特征提取主脚本 |
| `backend/tools/explore_mysql_schema.py` | MySQL schema 探查（备用） |
| `D:\tools\Cntlm\cntlm_bosch.ini` | cntlm 最小配置（SSPI 自动认证） |
| `features_102000000996_3d.parquet` | 验证输出（3天，986列） |
| `backend/.env` | 数据库连接凭据 |
