# cython: annotation_typing=False, infer_types=False, language_level=3
"""数据预处理器 — 按 sourceKey 前缀对原始数据执行 map-reduce 变换。

预处理后的数据完全替换原始 data，已配置的 sourceKey 不再保留原始 records。
目的：(1) Python 层精确统计，避免 LLM 计数错误；(2) 压缩上下文，去除冗余字段。

使用方式：
    from backend.utils.data_preprocessor import register, preprocess_sources

    # 在 clean_raw_data() 之后调用
    response_list = cleaned_data.get("response", [])
    preprocess_sources(response_list)

扩展方式：
    @register("yourSourceKeyPrefix_")
    def your_preprocessor(data: dict) -> dict | None:
        ...
"""

import re
from collections import defaultdict
from typing import Callable

PREPROCESSOR_REGISTRY: dict[str, Callable] = {}


def register(source_key_prefix: str):
    """装饰器：注册 sourceKey 预处理器。按前缀匹配，一个 sourceKey 只匹配第一个命中的注册项。"""

    def decorator(func):
        PREPROCESSOR_REGISTRY[source_key_prefix] = func
        return func

    return decorator


def preprocess_sources(response_list: list) -> list:
    """遍历 response[]，对匹配到的 sourceKey 执行预处理并替换 item["data"]。

    Args:
        response_list: clean_raw_data 之后的 response 数组，原地修改

    Returns:
        同 response_list（原地修改后的引用）
    """
    # 第一步：执行单 sourceKey 预处理器
    for item in response_list:
        if not isinstance(item, dict):
            continue

        sk = item.get("sourceKey", "")
        for prefix, preprocessor in PREPROCESSOR_REGISTRY.items():
            if sk.startswith(prefix):
                old_data = item.get("data", {})
                # 兼容 dict 和 list 两种 data 类型
                if isinstance(old_data, (dict, list)):
                    new_data = preprocessor(old_data)
                    if new_data is not None:
                        new_data["_preprocessed"] = True
                        item["data"] = new_data
                break  # 一个 sourceKey 只匹配一个预处理器

    # 第二步：执行跨 sourceKey 合并
    _merge_device_running_rates(response_list)

    return response_list


# ============================================================
# 内置预处理器
# ============================================================


@register("maintainTaskPage_")
def prep_maintain_task(data: dict) -> dict | None:
    """点检保养 → 按设备分组统计状态×执行结果，只保留统计 + 异常明细。

    输入：data.records[] — 原始点检保养任务列表
    输出：summary / byDevice / abnormalDetails（不含原始 records）
    """
    records = data.get("records", [])
    if not records:
        return None

    by_device: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    abnormal_details: list[dict] = []
    total = executed = closed = not_executed = abnormal = 0

    for r in records:
        total += 1
        status = r.get("status", "")
        # clean_raw_data 已删除空字符串字段，execResult 不存在时默认为空
        exec_result = r.get("execResult", "")
        device_name = r.get("deviceName", "")

        # 构造状态标签
        if status == "已执行":
            executed += 1
            label = f"已执行({exec_result if exec_result else '无结果'})"
        elif status == "已关闭":
            closed += 1
            label = f"已关闭({exec_result if exec_result else '无结果'})"
        elif status == "未执行":
            not_executed += 1
            label = "未执行"
        else:
            # "未开始" 等其它状态，原样保留
            label = status

        by_device[device_name][label] += 1

        # 提取点检异常明细（从 children 中过滤 execResult="异常" 的项）
        children = r.get("children", [])
        if isinstance(children, list):
            for c in children:
                if c.get("execResult") == "异常":
                    abnormal += 1
                    abnormal_details.append({
                        "deviceName": device_name,
                        "planName": r.get("planName", ""),
                        "standardName": r.get("standardName", ""),
                        "itemName": c.get("name", ""),
                        "content": c.get("content", ""),
                        "actValue": c.get("actValue", ""),
                    })

    return {
        "summary": {
            "total": total,
            "executed": executed,
            "closed": closed,
            "notExecuted": not_executed,
            "abnormal": abnormal,
        },
        "byDevice": [
            {
                "deviceName": name,
                "taskCount": sum(counts.values()),
                "statusText": " + ".join(
                    f"{k}×{v}" if v > 1 else k
                    for k, v in sorted(counts.items())
                ),
            }
            for name, counts in by_device.items()
        ],
        "abnormalDetails": abnormal_details,
    }


# ============================================================
# 工具函数
# ============================================================


def _parse_duration_to_minutes(s: str) -> int:
    """解析中文时长字符串为总分钟数。

    Examples:
        "3小时21分钟" → 201
        "45分钟" → 45
        "2小时" → 120
        "" → 0
    """
    if not s:
        return 0
    mins = 0
    h_match = re.search(r"(\d+)\s*小时", s)
    m_match = re.search(r"(\d+)\s*分钟", s)
    if h_match:
        mins += int(h_match.group(1)) * 60
    if m_match:
        mins += int(m_match.group(1))
    return mins


# ============================================================
# 跨 sourceKey 合并处理器
# ============================================================


def _merge_device_running_rates(response_list: list) -> None:
    """合并 deviceMonthRunningRate_d* 和 deviceDayRunningRate_d* 数据。

    将多个独立的设备数据合并为一个对象，提取公共数据（如 xaxis）减少重复。
    合并后删除原始的独立 sourceKey 项。

    Args:
        response_list: response 数组，原地修改
    """
    _merge_device_month_running_rates(response_list)
    _merge_device_day_running_rates(response_list)


def _merge_device_month_running_rates(response_list: list) -> None:
    """合并 deviceMonthRunningRate_d* 为 deviceMonthRunningRate_merged。

    提取公共的 xaxis 和 chartNames，每个设备只保留 seriesData。
    """
    # 收集所有 deviceMonthRunningRate_d* 项
    items_to_merge = []
    for i, item in enumerate(response_list):
        if not isinstance(item, dict):
            continue
        sk = item.get("sourceKey", "")
        if sk.startswith("deviceMonthRunningRate_d"):
            items_to_merge.append((i, item))

    if not items_to_merge:
        return

    # 提取公共数据（从第一个设备的图表数据）
    first_data = items_to_merge[0][1].get("data", {})
    charts = first_data.get("chartDataVoList", [])
    xaxis = charts[0].get("xaxis", []) if charts else []
    chart_names = [c.get("chartName", "") for c in charts]

    # 合并每个设备的数据
    devices = {}
    for _, item in items_to_merge:
        sk = item.get("sourceKey", "")
        device_id = sk.split("_d")[-1] if "_d" in sk else ""
        data_obj = item.get("data", {})

        # 保留汇总字段，图表只保留 seriesData
        device_data = {k: v for k, v in data_obj.items() if k != "chartDataVoList"}
        device_data["chartDataVoList"] = []
        for chart in data_obj.get("chartDataVoList", []):
            device_data["chartDataVoList"].append({
                "seriesData": chart.get("seriesData", [])
            })
        devices[device_id] = device_data

    # 构造合并后的数据
    merged_data = {
        "xaxis": xaxis,
        "chartNames": chart_names,
        "devices": devices,
        "_preprocessed": True,
    }

    # 删除原始项（从后往前删，避免索引偏移）
    indices_to_remove = sorted([i for i, _ in items_to_merge], reverse=True)
    for idx in indices_to_remove:
        response_list.pop(idx)

    # 添加合并后的项
    response_list.append({
        "sourceKey": "deviceMonthRunningRate_merged",
        "requestUrl": "",
        "data": merged_data,
    })


def _merge_device_day_running_rates(response_list: list) -> None:
    """合并 deviceDayRunningRate_d* 为 deviceDayRunningRate_merged。

    每个设备保留完整的班次数据，删除重复的时间字段。
    """
    # 收集所有 deviceDayRunningRate_d* 项
    items_to_merge = []
    for i, item in enumerate(response_list):
        if not isinstance(item, dict):
            continue
        sk = item.get("sourceKey", "")
        if sk.startswith("deviceDayRunningRate_d"):
            items_to_merge.append((i, item))

    if not items_to_merge:
        return

    # 合并每个设备的数据
    devices = {}
    for _, item in items_to_merge:
        sk = item.get("sourceKey", "")
        device_id = sk.split("_d")[-1] if "_d" in sk else ""
        data_obj = item.get("data", {})
        devices[device_id] = data_obj

    # 构造合并后的数据
    merged_data = {
        "devices": devices,
        "_preprocessed": True,
    }

    # 删除原始项（从后往前删，避免索引偏移）
    indices_to_remove = sorted([i for i, _ in items_to_merge], reverse=True)
    for idx in indices_to_remove:
        response_list.pop(idx)

    # 添加合并后的项
    response_list.append({
        "sourceKey": "deviceDayRunningRate_merged",
        "requestUrl": "",
        "data": merged_data,
    })


# ============================================================
# 共享预处理入口（供各 worker 模块调用）
# ============================================================


def preprocess_payload(payload: dict) -> str:
    """对原始 payload 执行 clean + map-reduce 预处理，返回序列化 JSON 字符串。

    各 worker 模块在调用 generate_reports_stream 之前调用此函数，
    将返回值同时传给 generator（跳过重复计算）和 db.upsert_report（填充 agent_response_processed）。

    Args:
        payload: 原始 payload 字典（含 response[] 等字段）

    Returns:
        预处理后的 JSON 字符串（ensure_ascii=False, indent=2）
    """
    import json
    from backend.utils.data_cleaner import clean_raw_data

    cleaned = clean_raw_data(payload)
    response_list = cleaned.get("response", [])
    if isinstance(response_list, list):
        preprocess_sources(response_list)

    return json.dumps(cleaned, ensure_ascii=False, indent=2)
