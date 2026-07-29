"""测试生成班组组长绩效对比报告。

该脚本不会修改现有报告链路，仅用于验证：
1. 将班组排班信息注入现有早会日报数据；
2. 复用项目的数据预处理逻辑压缩模型输入；
3. 调用 OpenAI 兼容接口生成组长维度对比报告。

示例：
    python scripts/test_leader_performance_report.py \
        --data logs/其他工序日报数据 \
        --schedule logs/班组班次 \
        --dry-run

    python scripts/test_leader_performance_report.py \
        --data logs/其他工序日报数据 \
        --schedule logs/班组班次
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = PROJECT_ROOT / "logs" / "数据结构"
DEFAULT_SCHEDULE_PATH = PROJECT_ROOT / "logs" / "班组班次"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "logs" / "leader_performance_test"

DAY_CLASS_NAMES = {"白班", "早班", "早班（单班次）", "早班(单班次)"}
NIGHT_CLASS_NAMES = {"夜班", "晚班"}

REPORT_PROMPT = """你是一名制造业精益生产数据分析专家。请根据输入数据生成
《早会日报——班组组长当日绩效对比分析报告》。

【数据说明】
1. meta.period 是生产日期。
2. teamScheduleContext 是预处理程序根据生产日期、产线和排班表注入的班组信息。
3. response 是该工序现有早会日报数据，可能包含设备运转率、质量检验、点检、报警、
   报修、产量和能耗等数据。
4. 白班数据归属 classCode=DAY 的班组和组长，夜班数据归属 classCode=NIGHT 的班组和组长。
5. 夜班可能跨自然日，但仍按 meta.period 所代表的生产日期归属。

【强制规则】
1. 只能使用输入数据中的事实，不得虚构人员、指标、原因、异常或处理措施。
2. 不得把“无数据”解释为0；没有数据时明确写“无数据，暂不比较”。
3. 百分率之差必须使用“百分点”。
4. 运转率低但没有停机原因证据时，只能描述“非运行时间较长”，不得推断为人员管理问题。
5. 历史报修不得当作当班新增报修；只有发生时间落入班次的数据才能归属当班。
6. 对比时优先使用相同设备的白班与夜班数据。
7. 如果数据只有一个班次，必须说明不具备白夜班对比条件，不得编造另一班次。
8. 若双方均未达到目标，即使一方数值更高，也必须说明双方均未达标。
9. 不计算没有明确规则的综合分，不给组长强行排名。
10. 建议必须对应到具体班组、设备、指标或异常，避免“加强管理”等空泛表述。
11. 输出中文 Markdown，不展示 JSON 字段名，不输出分析过程。

【输出结构】
## 班组组长绩效对比分析报告（生产日期）

### 一、当日对比结论
说明白班、夜班分别由哪个班组和组长负责，概括双方主要优势、差距和未达标项。

### 二、核心指标对比
使用 Markdown 表格展示：
指标｜目标值｜白班组长｜夜班组长｜差异｜结论

根据实际存在的数据选择运转率、质量合格率、产量或计划完成率、点检执行情况、
报警次数、参数报警次数、新增报修数等指标。无数据填写“无数据”。

### 三、设备表现对比
按相同设备比较白班和夜班，重点说明差异明显或存在异常的设备。

### 四、质量、点检与设备异常
列出有数据证据的质量不合格、点检异常、设备报警、参数报警和报修情况；
没有异常时明确说明。

### 五、组长当班表现
分别评价两位组长当班的优势、未达标项及需要跟进的事项。
评价必须客观，不得把设备客观故障直接认定为组长责任。

### 六、次日改善建议
输出2至5条可检查、可执行的建议。

### 七、数据口径说明
说明生产日期、班组映射来源、设备范围、数据缺失情况和比较限制。

【输入数据】
{data_sources}
"""


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    Returns:
        命令行参数对象。
    """
    parser = argparse.ArgumentParser(description="测试生成班组组长绩效对比报告")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH, help="早会日报原始 JSON 文件")
    parser.add_argument("--schedule", type=Path, default=DEFAULT_SCHEDULE_PATH, help="班组班次 JSON 文件")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="测试结果输出目录")
    parser.add_argument("--date", help="覆盖报告生产日期，格式 YYYY-MM-DD")
    parser.add_argument("--line-id", type=int, help="覆盖日报中的 lineId")
    parser.add_argument("--dry-run", action="store_true", help="仅生成模型输入，不调用大模型")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    """读取 JSON 文件。

    Args:
        path: JSON 文件路径。

    Returns:
        JSON 根对象。

    Raises:
        ValueError: 文件内容不是 JSON 对象。
    """
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"JSON 根节点必须是对象：{path}")
    return data


def extract_report_date(payload: dict[str, Any], override_date: str | None) -> str:
    """提取生产日期。

    Args:
        payload: 日报原始数据。
        override_date: 命令行覆盖日期。

    Returns:
        YYYY-MM-DD 格式的生产日期。

    Raises:
        ValueError: 未找到生产日期。
    """
    if override_date:
        return override_date
    meta = payload.get("meta") or {}
    report_date = meta.get("period") or meta.get("reportDate") or meta.get("report_date")
    if not report_date:
        raise ValueError("日报数据中缺少 meta.period，请通过 --date 指定生产日期")
    return str(report_date)


def extract_line_id(payload: dict[str, Any], override_line_id: int | None) -> int:
    """提取产线ID。

    Args:
        payload: 日报原始数据。
        override_line_id: 命令行覆盖产线ID。

    Returns:
        产线ID。

    Raises:
        ValueError: 未找到产线ID。
    """
    if override_line_id is not None:
        return override_line_id
    meta = payload.get("meta") or {}
    line_id = meta.get("lineId")
    if line_id in (None, ""):
        raise ValueError("日报数据中缺少 meta.lineId，请通过 --line-id 指定产线ID")
    return int(line_id)


def normalize_class(class_id: Any, class_name: str) -> str:
    """将班次统一为 DAY 或 NIGHT。

    Args:
        class_id: 原班次ID。
        class_name: 原班次名称。

    Returns:
        DAY、NIGHT 或 UNKNOWN。
    """
    normalized_name = class_name.strip()
    if normalized_name in DAY_CLASS_NAMES or str(class_id) == "1":
        return "DAY"
    if normalized_name in NIGHT_CLASS_NAMES or str(class_id) == "2":
        return "NIGHT"
    return "UNKNOWN"


def split_team_and_leader(team_name: str) -> tuple[str, str]:
    """从现有班组名称中临时提取组长姓名。

    Args:
        team_name: 例如“铸带线A班组(陈明浪)”。

    Returns:
        不含组长括号的班组名称和组长姓名。
    """
    match = re.search(r"[（(]\s*([^（）()]+?)\s*[）)]\s*$", team_name)
    if not match:
        return team_name.strip(), ""
    clean_team_name = team_name[: match.start()].strip()
    return clean_team_name, match.group(1).strip()


def find_schedule_for_date(schedule: Any, report_date: str) -> dict[str, Any] | None:
    """在班组的嵌套排班中查找指定日期。

    Args:
        schedule: schedule 字段。
        report_date: 生产日期。

    Returns:
        指定日期的排班对象，未找到时返回 None。
    """
    if not isinstance(schedule, dict):
        return None
    for day_schedule in schedule.values():
        if isinstance(day_schedule, dict) and day_schedule.get("schedulingDate") == report_date:
            return day_schedule
    return None


def build_team_context(
    schedule_payload: dict[str, Any],
    report_date: str,
    line_id: int,
) -> dict[str, Any]:
    """构造注入日报数据的班组上下文。

    Args:
        schedule_payload: 班组班次原始数据。
        report_date: 生产日期。
        line_id: 产线ID。

    Returns:
        标准化后的班组上下文。

    Raises:
        ValueError: 当前产线或日期没有可用排班。
    """
    records = ((schedule_payload.get("data") or {}).get("records") or [])
    if not isinstance(records, list):
        raise ValueError("班组班次数据中的 data.records 不是数组")

    teams: list[dict[str, Any]] = []
    available_lines: dict[int, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        record_line_id = record.get("lineId")
        if record_line_id not in (None, ""):
            available_lines[int(record_line_id)] = str(record.get("lineName") or "")
        if str(record_line_id) != str(line_id):
            continue

        day_schedule = find_schedule_for_date(record.get("schedule"), report_date)
        if not day_schedule:
            continue

        raw_team_name = str(record.get("teamName") or "")
        team_name, leader_name = split_team_and_leader(raw_team_name)
        devices = day_schedule.get("scheduledDevices") or []
        teams.append(
            {
                "teamId": record.get("teamId"),
                "teamName": team_name,
                "leaderName": leader_name,
                "organizationId": record.get("organizationId"),
                "classId": day_schedule.get("classId"),
                "className": day_schedule.get("className"),
                "classCode": normalize_class(day_schedule.get("classId"), str(day_schedule.get("className") or "")),
                "startTime": devices[0].get("startTime") if devices else None,
                "endTime": devices[0].get("endTime") if devices else None,
                "devices": [
                    {
                        "deviceId": device.get("deviceId"),
                        "deviceName": device.get("deviceName"),
                    }
                    for device in devices
                    if isinstance(device, dict)
                ],
            }
        )

    if not teams:
        available_text = "、".join(
            f"{available_line_id}({line_name})"
            for available_line_id, line_name in sorted(available_lines.items())
        )
        raise ValueError(
            f"班组班次中没有 productionDate={report_date}、lineId={line_id} 的排班；"
            f"当前文件可用产线：{available_text or '无'}"
        )

    teams.sort(key=lambda item: (item["classCode"] != "DAY", str(item.get("teamId") or "")))
    return {
        "productionDate": report_date,
        "lineId": line_id,
        "mappingSource": "班组班次测试数据",
        "teams": teams,
    }


def inject_team_context(
    payload: dict[str, Any],
    team_context: dict[str, Any],
) -> dict[str, Any]:
    """在原有日报数据上注入班组上下文。

    Args:
        payload: 原始日报数据。
        team_context: 标准化班组上下文。

    Returns:
        不修改原对象的增强日报数据。
    """
    enriched_payload = deepcopy(payload)
    enriched_payload["teamScheduleContext"] = team_context
    return enriched_payload


def load_project_env() -> None:
    """按项目现有优先级加载模型环境变量。"""
    try:
        from dotenv import load_dotenv
    except ImportError as error:
        raise ValueError("缺少 python-dotenv，请先安装项目依赖") from error

    env_candidates = [
        PROJECT_ROOT / "deploy" / "docker" / ".env",
        PROJECT_ROOT / "backend" / ".env",
        PROJECT_ROOT / ".env",
    ]
    for env_path in env_candidates:
        if env_path.is_file():
            load_dotenv(env_path, override=False)
            return
    load_dotenv(override=False)


def resolve_model_config() -> tuple[str, str, str]:
    """从项目环境变量解析 OpenAI 兼容模型配置。

    Returns:
        base_url、api_key、model。

    Raises:
        ValueError: 配置不完整。
    """
    provider = os.getenv("PROVIDER", "local_qwen3")
    provider_prefix = provider.upper()
    base_url = os.getenv(f"{provider_prefix}_BASE_URL", "")
    api_key = os.getenv(f"{provider_prefix}_API_KEY", "")
    model = os.getenv("MODEL") or os.getenv(f"{provider_prefix}_MODEL", "")
    if not base_url or not api_key or not model:
        raise ValueError(
            "模型配置不完整，请检查 PROVIDER 以及对应的 "
            f"{provider_prefix}_BASE_URL、{provider_prefix}_API_KEY、"
            f"{provider_prefix}_MODEL（或 MODEL）"
        )
    if "11434" in base_url and not base_url.rstrip("/").endswith("/v1"):
        base_url = f"{base_url.rstrip('/')}/v1"
    return base_url, api_key, model


def generate_report(preprocessed_data: str) -> str:
    """调用大模型生成报告。

    Args:
        preprocessed_data: 预处理后的日报 JSON 字符串。

    Returns:
        Markdown 报告。
    """
    try:
        from openai import OpenAI
    except ImportError as error:
        raise ValueError("缺少 openai，请先安装项目依赖") from error

    base_url, api_key, model = resolve_model_config()
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=600.0)
    prompt = REPORT_PROMPT.replace("{data_sources}", preprocessed_data)
    print(f"[模型] base_url={base_url}")
    print(f"[模型] model={model}")
    print(f"[模型] 提示词长度={len(prompt)}")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


def write_text(path: Path, content: str) -> None:
    """以UTF-8写入文本。

    Args:
        path: 输出路径。
        content: 文本内容。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    """执行测试流程。

    Returns:
        进程退出码。
    """
    args = parse_args()
    try:
        payload = load_json(args.data.resolve())
        schedule_payload = load_json(args.schedule.resolve())
        report_date = extract_report_date(payload, args.date)
        line_id = extract_line_id(payload, args.line_id)
        team_context = build_team_context(schedule_payload, report_date, line_id)
        enriched_payload = inject_team_context(payload, team_context)

        # 复用正式链路的预处理，测试结果更接近后续集成效果。
        sys.path.insert(0, str(PROJECT_ROOT))
        from backend.utils.data_preprocessor import preprocess_payload

        preprocessed_data = preprocess_payload(enriched_payload)
        output_dir = args.output_dir.resolve()
        enriched_path = output_dir / f"{report_date}_班组增强原始数据.json"
        model_input_path = output_dir / f"{report_date}_组长报告模型输入.json"
        write_text(enriched_path, json.dumps(enriched_payload, ensure_ascii=False, indent=2))
        write_text(model_input_path, preprocessed_data)

        print(f"[成功] 生产日期：{report_date}")
        print(f"[成功] lineId：{line_id}")
        for team in team_context["teams"]:
            print(
                f"[班组] {team['className']} -> {team['teamName']} / "
                f"{team['leaderName'] or '组长未解析'} / 设备数={len(team['devices'])}"
            )
        print(f"[输出] 增强数据：{enriched_path}")
        print(f"[输出] 模型输入：{model_input_path}")

        if args.dry_run:
            print("[完成] dry-run 模式未调用大模型")
            return 0

        load_project_env()
        report = generate_report(preprocessed_data)
        report_path = output_dir / f"{report_date}_班组组长绩效对比报告.md"
        write_text(report_path, report)
        print(f"[输出] 生成报告：{report_path}")
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"[失败] {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"[失败] 模型调用或报告生成异常：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
