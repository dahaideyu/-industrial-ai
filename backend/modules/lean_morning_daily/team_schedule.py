"""精益早会日报临时班组配置处理。

该模块只负责从本地配置中筛选候选班组并注入日报数据，不判断第四份报告
最终使用班组维度还是班次维度；分析维度由大模型结合日报数据自行判断。
"""

from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TEAM_SCHEDULE_PATH = PROJECT_ROOT / "backend" / "config" / "team_schedule.json"

DAY_CLASS_NAMES = {"白班", "早班", "早班（单班次）", "早班(单班次)"}
NIGHT_CLASS_NAMES = {"夜班", "晚班"}


def resolve_team_schedule_path(config_path: Path | str | None = None) -> Path:
    """解析临时班组配置路径。

    Args:
        config_path: 调用方指定路径；为空时读取环境变量和默认路径。

    Returns:
        解析后的绝对路径。
    """
    if config_path is not None:
        path = Path(config_path)
    else:
        configured_path = os.getenv("TEAM_SCHEDULE_CONFIG_PATH", "").strip()
        path = Path(configured_path) if configured_path else DEFAULT_TEAM_SCHEDULE_PATH

    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def load_team_schedule_config(
    config_path: Path | str | None = None,
    log: logging.Logger | None = None,
) -> dict[str, Any] | None:
    """读取临时班组配置。

    配置不可用时返回 ``None``，因为班组配置缺失不能阻断原有日报和班次报告。

    Args:
        config_path: 配置文件路径。
        log: 可选日志器。

    Returns:
        班组配置根对象；配置不可用时返回 ``None``。
    """
    active_log = log or logger
    path = resolve_team_schedule_path(config_path)
    if not path.is_file():
        active_log.info("[班组配置] 文件不存在，第四份报告将由模型按班次分析: %s", path)
        return None

    try:
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        active_log.warning("[班组配置] 读取失败，忽略临时配置: %s", error)
        return None

    if not isinstance(data, dict):
        active_log.warning("[班组配置] 根节点不是对象，忽略临时配置: %s", path)
        return None
    return data


def normalize_class_code(class_id: Any, class_name: str) -> str:
    """将配置中的班次统一成DAY或NIGHT。

    Args:
        class_id: 原始班次ID。
        class_name: 原始班次名称。

    Returns:
        ``DAY``、``NIGHT``或 ``UNKNOWN``。
    """
    normalized_name = class_name.strip()
    if normalized_name in DAY_CLASS_NAMES or str(class_id) == "1":
        return "DAY"
    if normalized_name in NIGHT_CLASS_NAMES or str(class_id) == "2":
        return "NIGHT"
    return "UNKNOWN"


def extract_team_and_leader(team_name: str) -> tuple[str, str]:
    """从临时配置的班组名称中提取组长。

    Args:
        team_name: 例如“铸带线A班组(陈明浪)”。

    Returns:
        清理后的班组名称和组长姓名。
    """
    match = re.search(r"[（(]\s*([^（）()]+?)\s*[）)]\s*$", team_name)
    if not match:
        return team_name.strip(), ""
    return team_name[: match.start()].strip(), match.group(1).strip()


def find_schedule_for_date(schedule: Any, report_date: str) -> dict[str, Any] | None:
    """从班组月度排班中查找指定生产日期。

    Args:
        schedule: 班组记录中的schedule字段。
        report_date: 日报生产日期。

    Returns:
        当日排班；不存在时返回 ``None``。
    """
    if not isinstance(schedule, dict):
        return None
    for value in schedule.values():
        if isinstance(value, dict) and str(value.get("schedulingDate") or "") == report_date:
            return value
    return None


def build_team_schedule_context(
    schedule_config: dict[str, Any],
    report_date: str,
    line_id: int,
) -> dict[str, Any] | None:
    """筛选指定日期和产线的候选班组。

    这里只做确定性筛选，不判断候选关系能否用于最终报告。

    Args:
        schedule_config: 临时班组配置。
        report_date: 日报生产日期。
        line_id: 日报产线ID。

    Returns:
        候选班组上下文；无候选记录时返回 ``None``。
    """
    records = ((schedule_config.get("data") or {}).get("records") or [])
    if not isinstance(records, list):
        return None

    teams: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or str(record.get("lineId")) != str(line_id):
            continue

        day_schedule = find_schedule_for_date(record.get("schedule"), report_date)
        if not day_schedule:
            continue

        raw_team_name = str(record.get("teamName") or "")
        team_name, leader_name = extract_team_and_leader(raw_team_name)
        devices = day_schedule.get("scheduledDevices") or []
        if not isinstance(devices, list):
            devices = []

        teams.append(
            {
                "teamId": record.get("teamId"),
                "teamName": team_name,
                "leaderName": leader_name,
                "organizationId": record.get("organizationId"),
                "classId": day_schedule.get("classId"),
                "className": day_schedule.get("className"),
                "classCode": normalize_class_code(
                    day_schedule.get("classId"),
                    str(day_schedule.get("className") or ""),
                ),
                "devices": [
                    {
                        "deviceId": device.get("deviceId"),
                        "deviceName": device.get("deviceName"),
                        "startTime": device.get("startTime"),
                        "endTime": device.get("endTime"),
                    }
                    for device in devices
                    if isinstance(device, dict)
                ],
            }
        )

    if not teams:
        return None

    teams.sort(
        key=lambda team: (
            team.get("classCode") != "DAY",
            str(team.get("teamId") or ""),
        )
    )
    return {
        "productionDate": report_date,
        "lineId": line_id,
        "mappingSource": "localTemporaryConfig",
        "teams": teams,
    }


def _extract_report_identity(payload: dict[str, Any]) -> tuple[str, int] | None:
    """从日报数据中提取生产日期和产线ID。

    Args:
        payload: 日报原始数据。

    Returns:
        ``(生产日期, 产线ID)``；字段不完整时返回 ``None``。
    """
    meta = payload.get("meta") or {}
    if not isinstance(meta, dict):
        return None

    report_date = (
        meta.get("period")
        or meta.get("reportDate")
        or meta.get("report_date")
    )
    line_id = meta.get("lineId")
    if not report_date or line_id in (None, ""):
        return None

    try:
        return str(report_date), int(line_id)
    except (TypeError, ValueError):
        return None


def inject_team_schedule_context(
    payload: dict[str, Any],
    config_path: Path | str | None = None,
    log: logging.Logger | None = None,
) -> dict[str, Any]:
    """将本地候选班组配置注入日报数据。

    Args:
        payload: 日报原始数据。
        config_path: 临时班组配置路径。
        log: 可选日志器。

    Returns:
        注入后的日报数据副本。无法注入时返回内容等价的副本。
    """
    active_log = log or logger
    enriched_payload = deepcopy(payload)
    identity = _extract_report_identity(enriched_payload)
    if identity is None:
        active_log.info("[班组配置] 日报缺少日期或lineId，不注入候选班组")
        enriched_payload.pop("teamScheduleContext", None)
        return enriched_payload

    schedule_config = load_team_schedule_config(config_path=config_path, log=active_log)
    if schedule_config is None:
        enriched_payload.pop("teamScheduleContext", None)
        return enriched_payload

    report_date, line_id = identity
    context = build_team_schedule_context(
        schedule_config=schedule_config,
        report_date=report_date,
        line_id=line_id,
    )
    if context is None:
        active_log.info(
            "[班组配置] 未筛选到候选班组，交由模型按班次分析: date=%s, lineId=%s",
            report_date,
            line_id,
        )
        enriched_payload.pop("teamScheduleContext", None)
        return enriched_payload

    enriched_payload["teamScheduleContext"] = context
    active_log.info(
        "[班组配置] 已注入候选班组: date=%s, lineId=%s, teams=%d",
        report_date,
        line_id,
        len(context["teams"]),
    )
    return enriched_payload
