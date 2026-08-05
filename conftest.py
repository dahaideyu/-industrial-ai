"""Pytest 配置：确保 backend/ 在 sys.path 上。

后端代码用 `from core.xxx import ...` 这类直接导入（不带 backend. 前缀），
因为 app.py 启动时会把 backend/ 加到 sys.path。测试不走 app.py，
所以需要在 conftest.py 中补上这个路径。
"""
import sys
from pathlib import Path

_backend_dir = str(Path(__file__).parent / "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
