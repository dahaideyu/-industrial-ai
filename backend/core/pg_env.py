# cython: annotation_typing=False, infer_types=False, language_level=3
"""PostgreSQL 连接参数的唯一来源。

为什么需要这个文件：历史上连库的环境变量有四套名字
    PG_*          —— 主力，代码里绝大多数地方用它
    KNB_PG_*      —— 知识库时期的遗留，.env 里白白重复一套
    DB_*          —— mqtt_etl 自己一套
    POSTGRES_*    —— 只剩 SSLMODE / CONNECT_TIMEOUT 两个连接选项
而且**默认值互相打架**：PG_HOST 有的默认本机、有的默认某台生产库地址；
PG_PASSWORD 有 4 处直接硬编码了生产口令。env 一旦漏配，不同模块会静默连到
不同的库，排查起来极痛苦，硬编码口令本身也是安全问题。

现在统一：对外只认 PG_*，默认值只在这里定义一次。
旧名仍可用但会打印一次废弃告警，方便老部署平滑过渡。
"""
import os
from typing import Any, Dict, Optional

# 已经告警过的旧变量名，避免每次连库都刷屏
_WARNED = set()

# 新名 -> 兼容的旧名（按优先级）
_ALIASES = {
    "PG_HOST": ("KNB_PG_HOST", "DB_HOST", "POSTGRES_HOST"),
    "PG_PORT": ("KNB_PG_PORT", "DB_PORT", "POSTGRES_PORT"),
    "PG_DB": ("KNB_PG_DB", "DB_NAME", "POSTGRES_DB"),
    "PG_USER": ("KNB_PG_USER", "DB_USER", "POSTGRES_USER"),
    "PG_PASSWORD": ("KNB_PG_PASSWORD", "DB_PASS", "POSTGRES_PASSWORD"),
    "PG_SSLMODE": ("POSTGRES_SSLMODE",),
    "PG_CONNECT_TIMEOUT": ("POSTGRES_CONNECT_TIMEOUT",),
}

# 默认值：只在这里定义一次。刻意不给 host/password 填生产值 ——
# 漏配时应该连不上并报错，而不是悄悄连到生产库。
_DEFAULTS = {
    "PG_HOST": "127.0.0.1",
    "PG_PORT": "5432",
    "PG_DB": "knowledge_base",
    "PG_USER": "zxzz",
    "PG_PASSWORD": "",
    "PG_CONNECT_TIMEOUT": "10",
}


def pg_env(name: str) -> Optional[str]:
    """按 新名 -> 旧名 -> 默认值 的顺序取一个连接参数。"""
    val = os.getenv(name)
    if val not in (None, ""):
        return val
    for old in _ALIASES.get(name, ()):
        old_val = os.getenv(old)
        if old_val not in (None, ""):
            if old not in _WARNED:
                _WARNED.add(old)
                print(f"[pg_env] 环境变量 {old} 已废弃，请改用 {name}（本次仍按 {old} 生效）")
            return old_val
    return _DEFAULTS.get(name)


def pg_params(**overrides: Any) -> Dict[str, Any]:
    """psycopg2.connect() 的参数字典。

    keepalives 默认打开：长查询/慢链路（企业代理隧道）下防止空闲超时断连，
    直连生产也无害。需要额外参数用关键字覆盖，例如：
        psycopg2.connect(**pg_params(connect_timeout=30))
    """
    params: Dict[str, Any] = {
        "host": pg_env("PG_HOST"),
        "port": int(pg_env("PG_PORT")),
        "dbname": pg_env("PG_DB"),
        "user": pg_env("PG_USER"),
        "password": pg_env("PG_PASSWORD"),
        "connect_timeout": int(pg_env("PG_CONNECT_TIMEOUT")),
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }
    # sslmode 不设就用驱动默认；本地经 cntlm 隧道访问时要设 disable
    # （SSL 会被企业代理 DPI 干扰，报 "SSL error: unexpected eof"）
    sslmode = pg_env("PG_SSLMODE")
    if sslmode:
        params["sslmode"] = sslmode
    params.update(overrides)
    return params


def pg_dsn() -> str:
    """给需要 DSN 字符串的场景（如 SQLAlchemy）用。"""
    p = pg_params()
    return (f"postgresql://{p['user']}:{p['password']}@"
            f"{p['host']}:{p['port']}/{p['dbname']}")
