# cython: annotation_typing=False, infer_types=False, language_level=3
"""中文嵌入模型 — 统一 ChromaDB 向量化

使用 HuggingFace 模型 ID（而非本地绝对路径），确保跨平台兼容。
如果有本地模型目录且内容完整，优先使用本地文件；否则从 HF 自动下载。
"""
import os

_embedding_function = None

_MODEL_ID = "BAAI/bge-small-zh-v1.5"


def _get_local_model_path():
    """动态计算项目目录下的本地模型路径"""
    import pathlib
    p = pathlib.Path(__file__).parent.parent.parent.parent / "backend" / "services" / "agentic_qa" / "bge-small-zh-v1.5"
    return str(p.resolve())


def get_embedding_function():
    """获取中文 embedding function（懒加载，单例）

    优先使用本地模型目录，不存在时使用 HF 模型 ID（自动下载缓存）。
    HF 模型 ID 存储在 ChromaDB 元数据中，不受操作系统路径影响。
    """
    global _embedding_function
    if _embedding_function is not None:
        return _embedding_function

    from chromadb.utils import embedding_functions
    from backend.core.agentic_qa.logger import get_logger

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SSL_VERIFY", "1")
    os.environ.setdefault("CURL_CA_BUNDLE", "")
    os.environ.setdefault("REQUESTS_CA_BUNDLE", "")

    local = _get_local_model_path()
    if os.path.isdir(local) and os.path.isfile(os.path.join(local, "model.safetensors")):
        # 本地模型存在且完整，直接使用
        model_name = local
    else:
        # 本地模型不存在，使用 HF ID（自动下载到 ~/.cache/huggingface/）
        model_name = _MODEL_ID

    try:
        _embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_name,
            device="cpu",
        )
        get_logger("core.embeddings").info(
            f"Chinese embedding loaded: {model_name}"
        )
    except Exception as e:
        _embedding_function = embedding_functions.DefaultEmbeddingFunction()
        get_logger("core.embeddings").warning(
            f"Chinese embedding failed ({e}), falling back to all-MiniLM-L6-v2"
        )

    return _embedding_function
