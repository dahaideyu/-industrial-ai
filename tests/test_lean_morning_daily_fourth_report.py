"""精益早会日报第四份报告映射测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from backend.clients.upstream_client import UpstreamClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path) -> ModuleType:
    """直接加载纯模块，避免测试环境提前导入Web依赖。

    Args:
        name: 临时模块名称。
        path: 模块文件路径。

    Returns:
        已加载模块。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report_fields_module = _load_module(
    "lean_morning_daily_report_fields",
    PROJECT_ROOT / "backend" / "modules" / "lean_morning_daily" / "report_fields.py",
)
map_reports_to_fields = report_fields_module.map_reports_to_fields

fourth_report_config_module = _load_module(
    "lean_morning_daily_fourth_report_config",
    PROJECT_ROOT / "backend" / "modules" / "lean_morning_daily" / "fourth_report_config.py",
)
is_fourth_report_enabled = fourth_report_config_module.is_fourth_report_enabled
resolve_template_limit = fourth_report_config_module.resolve_template_limit


def test_fourth_report_maps_to_local_team_compare_field() -> None:
    """第四份报告应映射到本地字段，前三份回调字段保持不变。"""
    reports = [
        {"content": "基础日报", "citations": []},
        {"content": "趋势分析", "citations": []},
        {"content": "改善建议", "citations": [{"source": "知识库"}]},
        {"content": "班次或班组对比", "citations": []},
    ]

    result = map_reports_to_fields(reports)

    assert result["markdownContent"] == "基础日报"
    assert result["summaryMarkdown"] == "趋势分析"
    assert result["kbReportMarkdown"] == "改善建议"
    assert result["teamCompareMarkdown"] == "班次或班组对比"


def test_evening_report_does_not_require_fourth_report() -> None:
    """傍晚版只生成基础日报时，第四份报告应标记为跳过。"""
    result = map_reports_to_fields(
        [{"content": "傍晚基础日报", "citations": []}],
        template_limit=1,
    )

    assert result["markdownContent"] == "傍晚基础日报"
    assert result["teamCompareMarkdown"] == "傍晚版仅生成基础日报（此报告无需生成）"


def test_fourth_report_can_be_disabled_by_base_configuration() -> None:
    """关闭基地开关时，无论调用方请求多少份报告，最多只生成前三份。"""
    assert is_fourth_report_enabled("false") is False
    assert resolve_template_limit(None, fourth_report_enabled=False) == 3
    assert resolve_template_limit(4, fourth_report_enabled=False) == 3


def test_fourth_report_is_disabled_when_configuration_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺失环境变量时，第四份报告默认关闭。"""
    monkeypatch.delenv("LEAN_MORNING_DAILY_FOURTH_REPORT_ENABLED", raising=False)

    assert is_fourth_report_enabled() is False


def test_fourth_report_can_be_enabled_by_base_configuration() -> None:
    """开启基地开关时，保留调用方原有的模板数量限制。"""
    assert is_fourth_report_enabled("true") is True
    assert resolve_template_limit(None, fourth_report_enabled=True) is None
    assert resolve_template_limit(4, fourth_report_enabled=True) == 4


def test_callback_complete_includes_fourth_report_field() -> None:
    """成功回调应把第四份报告写入teamCompareMarkdown字段。"""
    captured_request: dict[str, Any] = {}

    class FakeResponse:
        """提供回调客户端所需的最小响应接口。"""

        def raise_for_status(self) -> None:
            """模拟HTTP成功响应。"""

        def json(self) -> dict[str, Any]:
            """返回上游业务成功响应。"""
            return {"code": 200, "msg": "ok"}

    def fake_request(method: str, path: str, **kwargs: Any) -> FakeResponse:
        """捕获请求体，验证字段实际进入HTTP回调。"""
        captured_request.update({"method": method, "path": path, **kwargs})
        return FakeResponse()

    client = UpstreamClient(base_url="http://upstream.example", mock=False)
    client._request_with_retry = fake_request  # type: ignore[method-assign]

    client.callback_complete(
        report_id=7,
        status="0",
        team_compare_markdown="班次或班组对比",
    )

    assert captured_request["method"] == "POST"
    assert captured_request["path"] == "/report/ai-agent/callback/complete"
    assert captured_request["json"]["teamCompareMarkdown"] == "班次或班组对比"


def test_fourth_report_prompt_contains_auditable_scoring_rules() -> None:
    """第四份报告提示词应包含可复核评分及跨日班次口径。"""
    prompt_path = (
        PROJECT_ROOT
        / "backend"
        / "modules"
        / "lean_morning_daily"
        / "prompts"
        / "lean_morning_daily_report04.txt"
    )
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "设备效率 | 35分" in prompt
    assert "质量表现 | 25分" in prompt
    assert "点检执行与闭环 | 15分" in prompt
    assert "设备异常响应 | 15分" in prompt
    assert "报修闭环 | 10分" in prompt
    assert "综合得分 = 各可评分维度实际得分之和 ÷ 可计分权重之和 × 100" in prompt
    assert "次日00:00至06:00的记录归属于前一生产日夜班" in prompt
    assert "`inspectionMonthlyRateByDevice`属于月度统计口径，不得用于当前生产日质量评分" in prompt


def test_fourth_report_prompt_enforces_markdown_only_output() -> None:
    """第四份报告必须从Markdown标题开始，且禁止对话式开场和技术字段名。"""
    prompt_path = (
        PROJECT_ROOT
        / "backend"
        / "modules"
        / "lean_morning_daily"
        / "prompts"
        / "lean_morning_daily_report04.txt"
    )
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "只输出最终报告正文" in prompt
    assert "输出的第一个非空字符必须是`##`" in prompt
    assert "## 班次/班组绩效对比分析报告（实际生产日期）" in prompt
    assert "严禁出现“好的”" in prompt
    assert "九个固定章节使用三级标题`###`" in prompt
    assert "不得使用HTML标签" in prompt
    assert "正文不得出现任何字段名、接口名或数据结构名称" in prompt
    assert "必须改写为“班组排班候选信息”" in prompt
