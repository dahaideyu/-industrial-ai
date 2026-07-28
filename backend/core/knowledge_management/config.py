# cython: annotation_typing=False, infer_types=False, language_level=3
"""知识库管理模块配置

本模块的依赖服务（PostgreSQL / Redis / MinIO）已升级为系统级共享配置，
未来 agentic_qa / device_param / device_warning 等模块都会统一使用这套配置。

向后兼容：仍支持旧的 KNB_PG_* / KNB_REDIS_URL / KNB_MINIO_* 命名（旧名 → 新名映射）。
"""
import os
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings


# 解析 env_file 绝对路径：项目根目录下的 docker/.env
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_ENV_FILE = os.path.join(_PROJECT_ROOT, "docker", ".env")
if not os.path.isfile(_DEFAULT_ENV_FILE):
    _DEFAULT_ENV_FILE = "docker/.env"

# 手动加载 .env 文件（Pydantic v2 的 Config 类不支持 env_file，需要用 dotenv 预加载）
try:
    from dotenv import load_dotenv
    load_dotenv(_DEFAULT_ENV_FILE, override=False)
except ImportError:
    pass  # dotenv 未安装时跳过


def _env(name: str, *aliases: str, default: str = "") -> str:
    """按优先级读取环境变量：新名 → 旧别名 → 默认值。"""
    for n in (name, *aliases):
        v = os.getenv(n)
        if v:
            return v
    return default


def _env_int(name: str, *aliases: str, default: int = 0) -> int:
    for n in (name, *aliases):
        v = os.getenv(n)
        if v:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return default


def _get_llm_defaults():
    """根据 PROVIDER 环境变量获取 LLM 默认配置"""
    provider = os.getenv("PROVIDER", "deepseek").upper()
    return {
        "api_key": os.getenv(f"{provider}_API_KEY", ""),
        "base_url": os.getenv(f"{provider}_BASE_URL", ""),
        "model": os.getenv(f"{provider}_MODEL", ""),
    }


# 初始化时获取 LLM 默认配置
_llm_defaults = _get_llm_defaults()


class Settings(BaseSettings):
    enable_knowledge_base: bool = False

    # ---- 系统级共享 PostgreSQL（与 device_param / device_warning / maintenance_report 等模块共用）----
    # 字段保留 PG_* 新名，运行时通过 property 兼容旧 KNB_PG_* / 顶级 POSTGRES_*
    pg_host: str = Field(default="localhost", alias="PG_HOST")
    pg_port: int = Field(default=5432, alias="PG_PORT")
    pg_db: str = Field(default="knowledge_base", alias="PG_DB")
    pg_user: str = Field(default="zxzz", alias="PG_USER")
    pg_password: str = Field(default="", alias="PG_PASSWORD")

    # ---- LLM 配置（根据 PROVIDER 环境变量动态读取）----
    deepseek_api_key: str = Field(default=_llm_defaults["api_key"], alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default=_llm_defaults["base_url"], alias="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field(default=_llm_defaults["model"], alias="DEEPSEEK_MODEL")

    # ---- RAGFlow ----
    ragflow_base_url: str = Field(default="", alias="RAGFLOW_BASE_URL")
    ragflow_api_key: str = Field(default="", alias="RAGFLOW_API_KEY")
    ragflow_embedding_model: str = Field(default="text-embedding-v4@Tongyi-Qianwen@Tongyi-Qianwen", alias="RAGFLOW_EMBEDDING_MODEL")

    # ---- 知识库业务配置（保留 KNB_ 前缀，因为是模块专属概念）----
    knb_base_name: str = Field(default="江西基地", alias="KNB_BASE_NAME")
    knb_sync_enabled: bool = Field(default=True, alias="KNB_SYNC_ENABLED")
    knb_sync_api_key: str = Field(default="changeme", alias="KNB_SYNC_API_KEY")

    # ---- AQA 业务数据库（MySQL，agentic_qa 查询设备类型用）----
    aqa_mysql_host: str = Field(default="", alias="AQA_MYSQL_HOST")
    aqa_mysql_port: int = Field(default=3306, alias="AQA_MYSQL_PORT")
    aqa_mysql_user: str = Field(default="", alias="AQA_MYSQL_USER")
    aqa_mysql_password: str = Field(default="", alias="AQA_MYSQL_PASSWORD")
    aqa_mysql_database: str = Field(default="", alias="AQA_MYSQL_DATABASE")

    # ---- 视觉模型（合规性文档检测）----
    dashscope_api_key: str = Field(default="", alias="DASHSCOPE_API_KEY")
    dashscope_base_url: str = Field(default="https://dashscope.aliyun.com/compatible-mode/v1", alias="DASHSCOPE_BASE_URL")
    vision_model: str = Field(default="qwen-vl-plus", alias="VISION_MODEL")
    vision_timeout: float = Field(default=120.0, alias="VISION_TIMEOUT")

    @property
    def ragflow_api_url(self):
        """兼容旧代码，实际读取 RAGFLOW_BASE_URL"""
        return self.ragflow_base_url

    @property
    def database_url(self) -> str:
        """系统级共享 PostgreSQL 连接串。
        优先级：PG_* → KNB_PG_*（旧）→ 字段默认值
        """
        host = _env("PG_HOST", "KNB_PG_HOST", default=self.pg_host)
        port = _env_int("PG_PORT", "KNB_PG_PORT", default=self.pg_port)
        user = _env("PG_USER", "KNB_PG_USER", default=self.pg_user)
        password = _env("PG_PASSWORD", "KNB_PG_PASSWORD", default=self.pg_password)
        db = _env("PG_DB", "KNB_PG_DB", default=self.pg_db)
        encoded_password = quote_plus(password)
        return f"postgresql://{user}:{encoded_password}@{host}:{port}/{db}"

    @property
    def redis_url(self) -> str:
        """系统级共享 Redis URL。
        优先级：REDIS_URL（新）→ KNB_REDIS_URL（旧）→ 字段默认值
        """
        return _env("REDIS_URL", "KNB_REDIS_URL", default="redis://localhost:6379/1")

    @property
    def minio_endpoint(self) -> str:
        return _env("MINIO_ENDPOINT", "KNB_MINIO_ENDPOINT", default="localhost:9000")

    @property
    def minio_access_key(self) -> str:
        return _env("MINIO_ACCESS_KEY", "KNB_MINIO_ACCESS_KEY", default="")

    @property
    def minio_secret_key(self) -> str:
        return _env("MINIO_SECRET_KEY", "KNB_MINIO_SECRET_KEY", default="")

    @property
    def minio_bucket(self) -> str:
        return _env("MINIO_BUCKET", "KNB_MINIO_BUCKET", default="knowledge-base")

    class Config:
        env_file = _DEFAULT_ENV_FILE
        case_sensitive = False
        extra = "ignore"


settings = Settings()

# KNB_LOCATION 覆盖 KNB_BASE_NAME（优先级更高）
_loc = os.getenv("KNB_LOCATION")
if _loc:
    settings.knb_base_name = _loc
