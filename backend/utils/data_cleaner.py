# cython: annotation_typing=False, infer_types=False, language_level=3
"""上游原数据清洗工具

在数据注入 LLM 上下文之前，对上游返回的原始 payload 进行三步清洗：
1. 递归删除空值字段（"" / null / None）
2. 过滤指定的 sourceKey
3. 剥离 HTTP 包装层（requestUrl / msg / code）
"""

from typing import Any

# 需要从 response[] 中排除的 sourceKey 前缀
EXCLUDED_SOURCE_KEY_PREFIXES = (
    "workshopTree_",
    "mesProcedureList_",
)

# 兼容旧代码引用
EXCLUDED_SOURCE_KEYS = frozenset({
    "workshopTree_w32",
    "mesProcedureList_w32",
})


def clean_raw_data(data: dict) -> dict:
    """清洗上游原始数据，返回清洗后的新 dict（不修改原始对象）。

    Args:
        data: 上游返回的原始 payload 字典

    Returns:
        清洗后的新字典
    """
    import copy
    cleaned = copy.deepcopy(data)

    # 步骤1: 递归删除空值字段
    cleaned = _remove_empty_fields(cleaned)

    # 步骤2: 过滤指定 sourceKey
    cleaned = _filter_source_keys(cleaned)

    # 步骤3: 剥离 HTTP 包装层
    cleaned = _strip_http_wrapper(cleaned)

    return cleaned


def _remove_empty_fields(obj: Any) -> Any:
    """递归删除值为空字符串或 None 的字段。

    对 dict：删除值为 "" / None 的键，并递归处理值。
    对 list：递归处理每个元素，跳过处理后变为空的 dict。
    其他类型原样返回。

    Args:
        obj: 任意 Python 对象

    Returns:
        清洗后的对象
    """
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            # 跳过空值字段
            if value is None or value == "":
                continue
            cleaned_value = _remove_empty_fields(value)
            # 递归清洗后若值变为空，也跳过
            if cleaned_value is None or cleaned_value == "":
                continue
            # 跳过清洗后为空的 dict
            if isinstance(cleaned_value, dict) and not cleaned_value:
                continue
            result[key] = cleaned_value
        return result

    if isinstance(obj, list):
        result = []
        for item in obj:
            cleaned_item = _remove_empty_fields(item)
            # 跳过 None / "" / 空 dict
            if cleaned_item is None or cleaned_item == "":
                continue
            if isinstance(cleaned_item, dict) and not cleaned_item:
                continue
            result.append(cleaned_item)
        return result

    return obj


def _filter_source_keys(data: dict) -> dict:
    """从 response[] 数组中移除匹配指定前缀的 sourceKey 的项。

    Args:
        data: 清洗中的 payload 字典

    Returns:
        过滤后的字典
    """
    response_list = data.get("response")
    if not isinstance(response_list, list):
        return data

    def _is_excluded(source_key: str) -> bool:
        """检查 sourceKey 是否匹配排除前缀"""
        return any(source_key.startswith(prefix) for prefix in EXCLUDED_SOURCE_KEY_PREFIXES)

    data["response"] = [
        item for item in response_list
        if isinstance(item, dict) and not _is_excluded(item.get("sourceKey", ""))
    ]
    return data


def _strip_http_wrapper(data: dict) -> dict:
    """剥离 HTTP 包装层。

    对 response[] 中每个项：
    - 删除 requestUrl 字段
    - 展开嵌套的 response 对象：提取 data，丢弃 msg 和 code

    Args:
        data: 清洗中的 payload 字典

    Returns:
        剥离 HTTP 包装后的字典
    """
    response_list = data.get("response")
    if not isinstance(response_list, list):
        return data

    for item in response_list:
        if not isinstance(item, dict):
            continue

        # 删除外层 requestUrl
        item.pop("requestUrl", None)

        # 展开嵌套的 response 对象，只保留 data
        nested_response = item.pop("response", None)
        if isinstance(nested_response, dict) and "data" in nested_response:
            item["data"] = nested_response["data"]

    return data
