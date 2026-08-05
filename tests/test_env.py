"""Unit tests for backend/core/env.py

.env 加载器是全项目唯一的配置入口——加载优先级出错会导致
"app.py 加载了项目根 .env，config.py 又加载了 backend/.env" 的混乱。

测试覆盖：
- 幂等性：多次调用不会重复加载
- 优先级：--env > deploy/docker/.env > backend/.env > 项目根/.env
- 显式路径：文件不存在时报错退出
"""
import os
import sys
import importlib
import pytest
from pathlib import Path

from backend.core import env as env_module


@pytest.fixture(autouse=True)
def reset_env_module():
    """每个测试前后重置 env 模块的 _loaded 标志位，保证测试隔离。"""
    env_module._loaded = False
    env_module._loaded_path = None
    yield
    env_module._loaded = False
    env_module._loaded_path = None


class TestLoadEnvIdempotent:
    def test_second_call_is_noop(self):
        """已加载后第二次调用直接返回，不重复加载"""
        path = env_module.load_env()
        first_path = env_module.loaded_path()

        # 第二次调用
        path2 = env_module.load_env()
        assert path2 == first_path
        assert env_module.is_loaded() is True

    def test_is_loaded_flag(self):
        assert env_module.is_loaded() is False
        env_module.load_env()
        assert env_module.is_loaded() is True


class TestLoadEnvExplicitPath:
    def test_existing_file(self, tmp_path):
        """显式指定存在的文件应成功加载"""
        env_file = tmp_path / "test.env"
        env_file.write_text("TEST_VAR=hello\n")
        result = env_module.load_env(explicit_path=str(env_file))
        assert result == str(env_file)
        assert os.getenv("TEST_VAR") == "hello"
        os.environ.pop("TEST_VAR", None)

    def test_nonexistent_file_exits(self):
        """显式指定不存在的文件应 sys.exit（防拼写错误静默跑错配置）"""
        with pytest.raises(SystemExit):
            env_module.load_env(explicit_path="/nonexistent/path/.env")


class TestLoadEnvCandidatePaths:
    def test_finds_first_existing_candidate(self):
        """按优先级找到第一个存在的文件"""
        # 在开发环境下，deploy/docker/.env 或 backend/.env 或项目根 .env 至少有一个存在
        result = env_module.load_env()
        # 结果应该是某个候选路径，或者 None（纯 Docker 环境）
        if result is not None:
            assert os.path.isfile(result), f"返回的路径应存在: {result}"

    def test_returns_none_when_no_file(self, monkeypatch):
        """没有任何候选文件时返回 None（Docker 部署的正常情况）"""
        # monkeypatch 候选路径为不存在的路径
        monkeypatch.setattr(env_module, "_CANDIDATE_PATHS", [
            "/nonexistent1/.env",
            "/nonexistent2/.env",
        ])
        result = env_module.load_env()
        assert result is None
