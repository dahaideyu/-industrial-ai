# Device MQTT ETL Service

从MQTT Broker采集设备报警数据并批量写入TimescaleDB的ETL服务。

## 架构

```
MQTT Broker → Python采集服务 → 消息处理缓冲区 → TimescaleDB
                    ↓
              本地日志/死信
```

## 功能特性

- MQTT消息订阅与自动重连（指数退避策略）
- JSON消息解析与点位展平
- 批量缓冲写入（按数量/时间触发）
- 后台定时刷新线程
- 异常数据死信保存
- 优雅关闭保障

## 安装

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或 .venv\Scripts\activate  # Windows

# 安装依赖
uv sync
# 或 pip install -e .
```

## 运行

```bash
python main.py
```

## Systemd部署

```bash
# 复制服务文件
sudo cp device-mqtt-etl.service /etc/systemd/system/

# 重载配置
sudo systemctl daemon-reload

# 启用并启动
sudo systemctl enable --now device-mqtt-etl

# 查看状态
sudo systemctl status device-mqtt-etl

# 查看日志
sudo journalctl -u device-mqtt-etl -f
```

## 多 Topic 架构

一个topic可以挂一个或多个「解析器 + BatchBuffer」，互不干扰（一个 handler 抛异常
不影响同 topic 上的其他 handler），在 `main.py` 里按 `Config.MQTT_TOPIC` /
`Config.MQTT_TOPIC_NH` 是否配置来决定订阅哪些：

| Topic (env) | 解析器 | 落库表 | 说明 |
|---|---|---|---|
| `MQTT_TOPIC`（如 `Alarm/chaowei/jxcw`） | `AlarmMessageParser` | `device_alarm_info` | 报警点位，结构固定，按点位展平 |
| `MQTT_TOPIC_NH`（如 `NH/chaowei/jxcw`） | `EnergyMessageParser` | `device_energy_info` | 电表能耗点位，结构已确认（11 台电表 × 31 点位，见 `docs/江西设备AI信息表.xlsx`「能耗参数」sheet），按点位展平 |
| `MQTT_TOPIC_NH`（同上，双写） | `RawMessageParser` | `device_nh_raw` | 同一条消息原样落库做兜底/审计 |

新增 topic 的思路：加一个 `Config.MQTT_TOPIC_XXX` + 对应 `Parser`/表，在
`main.py` 的 `routes` 里注册即可，`MQTTClient`/`BatchBuffer` 都是通用的，不用改。

### 排查未知topic的数据结构

以后如果又来一个结构未知的新 topic，可以用 `mqtt_monitor.py`
（不写库，纯抓包落文件）先摸清结构再写专属解析器：

```bash
python mqtt_monitor.py
# 消息会存到 ./mqtt_messages/<topic按/转下划线>_<时间戳>.json
```

也可以直接查 `device_nh_raw` 表的 `raw_json` 列（同一份数据，主服务已在跑的话不用额外抓包）。

## 数据库表

服务启动连接数据库时会自动执行 `CREATE TABLE IF NOT EXISTS`（见
`database.py` 的 `_ensure_schema`），表不存在会自动建好，**不需要手工建表**。
以下 DDL 仅供参考实际结构：

```sql
CREATE TABLE public.device_alarm_info (
    device_id varchar(255) NOT NULL,
    device_status varchar(255) NULL,
    point_uid int4 NULL,
    point_id varchar(255) NOT NULL,
    value_type varchar(255) NULL,
    point_value int4 NOT NULL,
    point_time timestamp NOT NULL,
    upload_cycle int4 NULL,
    south_driver_name varchar(255) NULL,
    "time" timestamp NULL,
    load_time timestamp NULL,
    raw_json jsonb NULL
);

-- NH topic 原样落库表（兜底/审计用，device_energy_info 才是结构化的主表）
CREATE TABLE public.device_nh_raw (
    id bigserial PRIMARY KEY,
    topic varchar(255) NOT NULL,
    raw_json jsonb NULL,
    raw_text text NULL,
    received_at timestamp NOT NULL,
    load_time timestamp NULL
);
CREATE INDEX idx_device_nh_raw_received_at ON public.device_nh_raw (received_at);

-- 电表能耗点位表。point_value 是电压/电流/功率/功率因数等连续量，用 numeric
-- 保留小数（不像 device_alarm_info.point_value 那样截断成整数）。
CREATE TABLE public.device_energy_info (
    device_id varchar(255) NOT NULL,
    device_status varchar(255) NULL,
    point_uid int4 NULL,
    point_id varchar(255) NOT NULL,
    point_value numeric(14,4) NULL,
    point_time timestamp NOT NULL,
    upload_cycle int4 NULL,
    south_driver_name varchar(255) NULL,
    "time" timestamp NULL,
    load_time timestamp NULL,
    raw_json jsonb NULL
);
```
