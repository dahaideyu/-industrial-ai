# cython: annotation_typing=False, infer_types=False, language_level=3
import os
from pydantic_settings import BaseSettings

# 手动加载 .env 文件（确保在 _get_llm_config 调用前环境变量已就绪）
try:
    from dotenv import load_dotenv
    # 按优先级加载：docker/.env → backend/.env → 项目根/.env
    _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _project_root = os.path.dirname(_backend_dir)
    for _env_path in [
        os.path.join(_project_root, "docker", ".env"),
        os.path.join(_backend_dir, ".env"),
        os.path.join(_project_root, ".env"),
    ]:
        if os.path.isfile(_env_path):
            load_dotenv(_env_path, override=False)
            break
except ImportError:
    pass


def _get_llm_config():
    """根据 PROVIDER 环境变量获取 LLM 配置"""
    provider = os.getenv("PROVIDER", "deepseek").upper()
    return {
        "api_key": os.getenv(f"{provider}_API_KEY", ""),
        "base_url": os.getenv(f"{provider}_BASE_URL", ""),
        "model": os.getenv(f"{provider}_MODEL", ""),
    }


# 初始化时获取 LLM 配置
_llm_config = _get_llm_config()


class Settings(BaseSettings):
    # LLM 配置（根据 PROVIDER 环境变量动态读取）
    deepseek_api_key: str = _llm_config["api_key"]
    deepseek_base_url: str = _llm_config["base_url"]
    deepseek_model: str = _llm_config["model"]

    # RAGFlow (复用 .env 通用配置)
    ragflow_base_url: str = ""
    ragflow_api_key: str = ""

    @property
    def ragflow_api_url(self):
        """兼容旧代码，实际读取 RAGFLOW_BASE_URL"""
        return self.ragflow_base_url

    # MySQL (AQA_ 前缀)
    aqa_mysql_host: str = "localhost"
    aqa_mysql_port: int = 3306
    aqa_mysql_user: str = "root"
    aqa_mysql_password: str = ""
    aqa_mysql_database: str = "jxcw"

    # Vanna (AQA_ 前缀)
    aqa_vanna_model: str = os.getenv("PROVIDER", "deepseek")
    aqa_vanna_chroma_path: str = "./backend/data/agentic_qa/vanna-knowledge"
    aqa_entity_chroma_path: str = "./backend/data/agentic_qa/entity-knowledge"

    # Neo4j (AQA_ 前缀)
    aqa_neo4j_uri: str = "neo4j://localhost:7687"
    aqa_neo4j_user: str = "neo4j"
    aqa_neo4j_password: str = "neo4j"
    aqa_graph_mapping_path: str = "backend/config/graph_mapping.yaml"

    # App (AQA_ 前缀)
    aqa_app_env: str = "development"
    aqa_app_secret_key: str = "dev-secret-key-change-in-production"
    # 留空则自动复用主 PostgreSQL 连接（PG_*/POSTGRES_* 环境变量）
    aqa_database_url: str = ""

    # 知识库问答（KBQA）
    kbqa_router_llm: str = _llm_config["model"]
    kbqa_router_timeout: float = 8.0
    kbqa_chat_timeout: float = 30.0
    kbqa_history_full_turns: int = 3
    kbqa_max_context_tokens: int = 6000
    kbqa_summary_model: str = _llm_config["model"]
    kbqa_session_idle_days: int = 7
    kbqa_chat_assistant_name_prefix: str = "user-"

    # 兼容性属性（保持旧代码可用）
    @property
    def mysql_host(self):
        return self.aqa_mysql_host

    @property
    def mysql_port(self):
        return self.aqa_mysql_port

    @property
    def mysql_user(self):
        return self.aqa_mysql_user

    @property
    def mysql_password(self):
        return self.aqa_mysql_password

    @property
    def mysql_database(self):
        return self.aqa_mysql_database

    @property
    def vanna_model(self):
        return self.aqa_vanna_model

    @property
    def vanna_chroma_path(self):
        return self.aqa_vanna_chroma_path

    @property
    def entity_chroma_path(self):
        return self.aqa_entity_chroma_path

    @property
    def neo4j_uri(self):
        return self.aqa_neo4j_uri

    @property
    def neo4j_user(self):
        return self.aqa_neo4j_user

    @property
    def neo4j_password(self):
        return self.aqa_neo4j_password

    @property
    def graph_mapping_path(self):
        return self.aqa_graph_mapping_path

    @property
    def app_env(self):
        return self.aqa_app_env

    @property
    def app_secret_key(self):
        return self.aqa_app_secret_key

    @property
    def database_url(self):
        return self.aqa_database_url

    @property
    def ragflow_chat_id(self):
        return ""  # 不再使用

    class Config:
        env_file = "docker/.env"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
