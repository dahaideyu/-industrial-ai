"""精益早会日报临时班组配置处理测试。"""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from types import ModuleType


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


team_schedule_module = _load_module(
    "lean_morning_daily_team_schedule",
    PROJECT_ROOT / "backend" / "modules" / "lean_morning_daily" / "team_schedule.py",
)
inject_team_schedule_context = team_schedule_module.inject_team_schedule_context


def _write_schedule(path: Path) -> None:
    """写入测试班组配置。

    Args:
        path: 配置文件路径。
    """
    schedule = {
        "data": {
            "records": [
                {
                    "teamId": 3,
                    "teamName": "铸带线A班组(陈明浪)",
                    "lineId": 1,
                    "lineName": "铸带线",
                    "organizationId": 51,
                    "schedule": {
                        "07/19": {
                            "schedulingDate": "2026-07-19",
                            "classId": 1,
                            "className": "白班",
                            "scheduledDevices": [
                                {
                                    "deviceId": 118,
                                    "deviceName": "1#铸带线",
                                    "startTime": "06:00",
                                    "endTime": "18:00",
                                }
                            ],
                        }
                    },
                },
                {
                    "teamId": 4,
                    "teamName": "铸带线B班组（陈昌武）",
                    "lineId": 1,
                    "lineName": "铸带线",
                    "organizationId": 52,
                    "schedule": {
                        "07/19": {
                            "schedulingDate": "2026-07-19",
                            "classId": 2,
                            "className": "夜班",
                            "scheduledDevices": [
                                {
                                    "deviceId": 118,
                                    "deviceName": "1#铸带线",
                                    "startTime": "18:00",
                                    "endTime": "06:00",
                                }
                            ],
                        }
                    },
                },
            ]
        }
    }
    path.write_text(json.dumps(schedule, ensure_ascii=False), encoding="utf-8")


def test_inject_team_schedule_context_adds_candidate_teams(tmp_path: Path) -> None:
    """匹配日期和产线时，应注入候选班组但不预判分析维度。"""
    schedule_path = tmp_path / "team_schedule.json"
    _write_schedule(schedule_path)
    payload = {
        "meta": {
            "period": "2026-07-19",
            "lineId": 1,
        },
        "response": [],
    }

    result = inject_team_schedule_context(payload, config_path=schedule_path)

    context = result["teamScheduleContext"]
    assert context["productionDate"] == "2026-07-19"
    assert context["lineId"] == 1
    assert [team["classCode"] for team in context["teams"]] == ["DAY", "NIGHT"]
    assert [team["leaderName"] for team in context["teams"]] == ["陈明浪", "陈昌武"]
    assert "performanceComparisonContext" not in result


def test_inject_team_schedule_context_keeps_payload_when_no_mapping(tmp_path: Path) -> None:
    """没有对应产线时，不应阻断班次维度报告。"""
    schedule_path = tmp_path / "team_schedule.json"
    _write_schedule(schedule_path)
    payload = {
        "meta": {
            "period": "2026-07-19",
            "lineId": 27,
        },
        "response": [{"sourceKey": "deviceDayRunningRate_merged"}],
    }

    result = inject_team_schedule_context(payload, config_path=schedule_path)

    assert "teamScheduleContext" not in result
    assert result["response"] == payload["response"]


def test_inject_team_schedule_context_keeps_payload_when_config_missing(tmp_path: Path) -> None:
    """配置文件缺失时，应返回原日报数据而不是抛出异常。"""
    payload = {
        "meta": {
            "period": "2026-07-19",
            "lineId": 1,
        },
        "response": [],
    }

    result = inject_team_schedule_context(
        payload,
        config_path=tmp_path / "missing.json",
    )

    assert "teamScheduleContext" not in result
