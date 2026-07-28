# cython: annotation_typing=False, infer_types=False, language_level=3
"""
设备参数 AI 分析服务
将运行时段内的参数数据压缩后提交给 LLM 分析
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

from openai import AsyncOpenAI
from core.config import CONFIG


def get_analysis_system_prompt(analyze_running_only: bool) -> str:
    if analyze_running_only:
        return """你是一位工业设备数据分析专家。你的任务是根据设备在"运行"状态下的参数数据，进行深入分析。

请分析以下内容：
1. **参数趋势**：各参数在运行时段内的变化趋势（稳定、上升、下降、波动）
2. **异常检测**：是否存在参数值超出正常范围的异常点或异常时段
3. **关联分析**：不同参数之间是否存在关联变化模式
4. **设备健康评估**：基于当前参数表现，评估设备运行状态是否正常
5. **维护建议**：如有异常，给出具体的排查方向和维护建议

注意：
- 基于实际数据进行分析，不要无中生有
- 对于数据量不足的参数，请注明数据有限
- 使用专业但易懂的语言"""
    else:
        return """你是一位工业设备数据分析专家。你的任务是根据设备在指定时间范围内的所有参数数据（包括运行和非运行状态），进行深入分析。

请分析以下内容：
1. **参数趋势**：各参数在整个时间范围内的变化趋势（稳定、上升、下降、波动）
2. **运行与非运行状态对比**：对比分析设备在运行和非运行状态下的参数差异
3. **异常检测**：是否存在参数值超出正常范围的异常点或异常时段
4. **关联分析**：不同参数之间是否存在关联变化模式
5. **设备健康评估**：基于当前参数表现，评估设备运行状态是否正常
6. **维护建议**：如有异常，给出具体的排查方向和维护建议

注意：
- 基于实际数据进行分析，不要无中生有
- 对于数据量不足的参数，请注明数据有限
- 使用专业但易懂的语言"""


def get_llm():
    return AsyncOpenAI(
        base_url=CONFIG["base_url"],
        api_key=CONFIG["api_key"],
        timeout=300.0
    )


def _format_running_periods(periods: List[Dict]) -> str:
    if not periods:
        return "  无运行时段数据"
    lines = []
    for i, p in enumerate(periods, 1):
        start = p.get("start_time", "?")
        end = p.get("end_time") or "至今"
        dur = p.get("duration")
        dur_str = f"（{dur}秒）" if dur is not None else ""
        lines.append(f"  第{i}段: {start} ~ {end} {dur_str}")
    return "\n".join(lines)


def _format_compressed_data(compressed: Dict) -> str:
    series = compressed.get("series", {})
    if not series:
        return "  (无参数数据)"

    parts = [f"数据时间范围: {compressed.get('start_time')} ~ {compressed.get('end_time')}（共{compressed.get('total_hours', 0):.1f}小时）"]
    parts.append(f"参数数量: {len(series)}")
    parts.append("")

    for pname, buckets in series.items():
        parts.append(f"--- {pname} ---")
        for b in buckets:
            parts.append(
                f"  [{b['hour']}] "
                f"avg={b['avg']} min={b['min']} max={b['max']} "
                f"std={b['std']} count={b['count']}"
            )
        parts.append("")

    return "\n".join(parts)


async def analyze_device_params(
    device_code: str,
    device_name: str,
    time_range: Dict,
    running_periods: List[Dict],
    compressed_data: Dict,
    analyze_running_only: bool = True,
) -> str:
    """
    对设备参数数据进行 AI 分析

    Returns:
        str: AI 分析结果文本
    """
    periods_text = _format_running_periods(running_periods)
    data_text = _format_compressed_data(compressed_data)

    if analyze_running_only:
        user_prompt = """## 设备信息
- 设备编号: {}
- 设备名称: {}
- 分析时间范围: {} ~ {}
- 分析模式: 仅分析运行状态数据

## 运行时段
{}

## 压缩后的参数数据（按小时聚合）
{}

请对以上数据进行全面分析，给出趋势、异常、关联、健康评估和维护建议。""".format(device_code, device_name or device_code, time_range.get('start_time'), time_range.get('end_time'), periods_text, data_text)
    else:
        user_prompt = """## 设备信息
- 设备编号: {}
- 设备名称: {}
- 分析时间范围: {} ~ {}
- 分析模式: 分析全部数据（包括运行和非运行状态）

## 运行时段
{}

## 压缩后的参数数据（按小时聚合）
{}

请对以上数据进行全面分析，特别关注运行与非运行状态的对比，给出趋势、异常、关联、健康评估和维护建议。""".format(device_code, device_name or device_code, time_range.get('start_time'), time_range.get('end_time'), periods_text, data_text)

    llm = get_llm()
    try:
        response = await llm.chat.completions.create(
            model=CONFIG["model"],
            messages=[
                {"role": "system", "content": get_analysis_system_prompt(analyze_running_only)},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 分析请求失败: {str(e)}"
