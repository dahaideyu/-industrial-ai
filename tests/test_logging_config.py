"""Unit tests for backend/core/logging_config.py

集中式日志配置的正确性直接影响生产排障能力——
如果 setup_logging 清不掉已有 handler，basicConfig 残留的格式会混进来。

测试覆盖：
- setup_logging: handler 数量、级别、格式
- StructuredFormatter: JSON 输出结构
- 噪音库降级
"""
import json
import logging
import pytest

from backend.core.logging_config import setup_logging, StructuredFormatter, _NOISY_LOGGERS


@pytest.fixture(autouse=True)
def restore_logging():
    """每个测试后恢复 root logger 的原始状态。"""
    original_handlers = logging.getLogger().handlers[:]
    original_level = logging.getLogger().level
    yield
    logging.getLogger().handlers = original_handlers
    logging.getLogger().setLevel(original_level)


class TestSetupLogging:
    def test_clears_existing_handlers(self):
        """setup_logging 应清除已有 handler（避免 basicConfig 残留）"""
        logging.basicConfig(level=logging.DEBUG)  # 先塞一个
        assert len(logging.getLogger().handlers) >= 1
        setup_logging()
        assert len(logging.getLogger().handlers) == 1

    def test_default_level_is_info(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        setup_logging()
        assert logging.getLogger().level == logging.INFO

    def test_custom_level_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        setup_logging()
        assert logging.getLogger().level == logging.DEBUG

    def test_invalid_level_falls_back_to_info(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "INVALID")
        setup_logging()
        assert logging.getLogger().level == logging.INFO

    def test_noisy_loggers_downgraded(self):
        """第三方噪音库应被降到 WARNING"""
        setup_logging()
        for name in _NOISY_LOGGERS:
            assert logging.getLogger(name).level == logging.WARNING


class TestStructuredFormatter:
    def test_json_output_structure(self):
        """JSON 输出应包含 timestamp/level/logger/message"""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.module",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="test message %s",
            args=("arg",),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "WARNING"
        assert parsed["logger"] == "test.module"
        assert parsed["message"] == "test message arg"
        assert "timestamp" in parsed

    def test_json_output_with_exception(self):
        """异常信息应包含在 JSON 输出中"""
        formatter = StructuredFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]
