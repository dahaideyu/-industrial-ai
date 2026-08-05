# cython: annotation_typing=False, infer_types=False, language_level=3
"""统一的 .env 加载入口（全项目唯一权威）。

历史上 app.py 和 core/config.py 各有一套独立的加载逻辑，优先级不同，
出现过"app.py 加载了项目根 .env，config.py 又加载了 backend/.env"导致
配置来源混乱的问题。本模块用幂等标志位收敛为一条路径。

加载优先级（首个存在的文件生效，override=False 不覆盖已有环境变量）：
  1. explicit_path  —— 调用方显式指定（如 app.py 的 --env 参数），文件不存在直接报错
  2. deploy/docker/.env —— Docker 部署场景
  3. backend/.env       —— 后端本地开发
  4. 项目根目录/.env    —— 项目级开发

设计要点：
  - override=False（dotenv 默认）：已存在于环境变量中的值优先。
    Docker 部署时 compose env_file 注入的值不被 .env 覆盖。
  - 幂等：首次调用真正加载，后续调用直接返回（防止 core/config.py
    在 app.py 之后导入时选到不同的文件造成二次加载）。
"""
import os
import sys
import dotenv

_loaded = False
_loaded_path: str | None = None

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_project_root = os.path.dirname(_backend_dir)

_CANDIDATE_PATHS = [
    os.path.join(_project_root, "deploy", "docker", ".env"),
    os.path.join(_backend_dir, ".env"),
    os.path.join(_project_root, ".env"),
]


def load_env(explicit_path: str | None = None) -> str | None:
    """加载 .env，返回实际加载的文件路径（未加载返回 None）。

    Args:
        explicit_path: 显式指定的配置文件路径。相对路径按项目根解析。
                       文件不存在则报错退出（防拼写错误静默跑错配置）。

    Returns:
        实际加载的 .env 文件绝对路径；未找到任何文件则返回 None。
    """
    global _loaded, _loaded_path
    if _loaded:
        return _loaded_path

    if explicit_path:
        path = explicit_path if os.path.isabs(explicit_path) else os.path.join(_project_root, explicit_path)
        if not os.path.exists(path):
            print(f"[错误] 配置文件不存在: {path}")
            sys.exit(1)
        dotenv.load_dotenv(path)
        _loaded = True
        _loaded_path = path
        print(f"[启动] 已加载配置文件: {path}")
        return path

    for path in _CANDIDATE_PATHS:
        if os.path.isfile(path):
            dotenv.load_dotenv(path)
            _loaded = True
            _loaded_path = path
            print(f"[启动] 已加载配置文件: {path}")
            return path

    print(f"[启动] 未找到 .env，使用环境变量中的配置（Docker 部署正常现象）")
    _loaded = True
    return None


def is_loaded() -> bool:
    return _loaded


def loaded_path() -> str | None:
    return _loaded_path
