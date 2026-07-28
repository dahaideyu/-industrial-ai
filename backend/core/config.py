# cython: annotation_typing=False, infer_types=False, language_level=3
import os
import sys
import dotenv

# 优先加载 docker/.env，然后是 backend/.env，最后是项目根目录/.env
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(backend_dir)
docker_env_path = os.path.join(project_root, "deploy", "docker", ".env")
backend_env_path = os.path.join(backend_dir, ".env")
project_env_path = os.path.join(project_root, ".env")

if os.path.isfile(docker_env_path):
    dotenv.load_dotenv(docker_env_path)
elif os.path.isfile(backend_env_path):
    dotenv.load_dotenv(backend_env_path)
elif os.path.isfile(project_env_path):
    dotenv.load_dotenv(project_env_path)
else:
    dotenv.load_dotenv()  # 兜底：尝试默认位置

CONFIG = {
    "provider": None,
    "model": None,
    "base_url": None,
    "api_key": None
}


def load_config():
    """
    从环境变量加载模型配置
    需要的环境变量:
      - PROVIDER: 模型供应商 (deepseek, qwen3, openai, local_qwen3)
      - MODEL: (可选) 覆盖默认模型名称
    """
    provider = os.getenv("PROVIDER")
    if not provider:
        raise ValueError("请设置 PROVIDER 环境变量 (如: deepseek, qwen3, openai, local_qwen3)")

    provider_upper = provider.upper()
    base_url_var = f"{provider_upper}_BASE_URL"
    api_key_var = f"{provider_upper}_API_KEY"
    model_var = f"{provider_upper}_MODEL"

    base_url = os.getenv(base_url_var)
    api_key = os.getenv(api_key_var)
    default_model = os.getenv(model_var)

    if not base_url:
        raise ValueError(f"请在 .env 文件中配置 {base_url_var}")
    if not api_key:
        raise ValueError(f"请在 .env 文件中配置 {api_key_var}")

    model = os.getenv("MODEL") or default_model
    if not model:
        raise ValueError(f"请设置 MODEL 环境变量或在 .env 中配置 {model_var}")

    CONFIG["provider"] = provider
    CONFIG["model"] = model
    CONFIG["base_url"] = base_url
    CONFIG["api_key"] = api_key

    print(f"[配置] 已加载模型配置:")
    print(f"[配置]   供应商: {provider}")
    print(f"[配置]   模型: {model}")
    print(f"[配置]   API 地址: {base_url}")


try:
    load_config()
except Exception as e:
    print(f"[错误] 配置加载失败: {e}")
    sys.exit(1)
