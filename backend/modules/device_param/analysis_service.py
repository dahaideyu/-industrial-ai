# cython: annotation_typing=False, infer_types=False, language_level=3
"""
设备参数 AI 分析服务
将运行时段内的参数数据压缩后提交给 LLM 分析
支持知识库增强（从 RAGFlow 检索设备工艺文档作为分析参考）
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.config import CONFIG, get_llm_client

_kb_executor = ThreadPoolExecutor(max_workers=1)


_MACRO_MICRO_FRAMEWORK = """你是一位工业设备"设备脉搏"效能分析专家。设备脉搏＝设备的生产循环规律，每一次脉搏对应
一次完整的生产动作循环，是所有效能分析的基础；若数据中出现"阶段0"，那是非正常阶段，不计入统计，
所有阶段相关统计只从阶段1开始。

请严格按以下两层框架输出分析，两层都要有，不要合并或遗漏：

## 宏观层（面向运营管理与人员考核）
1. 时间切分：把分析时段切分为"节拍内"（设备真实运行、创造价值的时间）与"节拍外"（停机、待机等
   非增值时间），给出二者占比。
2. 核心指标：给出设备真实资产利用率（运行时长/总时长）、有效能耗与无效能耗（停机空耗）的对比、
   产量相关表现（如数据可推断）。
3. 结论要能直接支持班组/车间的绩效考核：明确指出低效具体发生在哪些时间段、初步根因是什么。
4. 不管当前是产能不足要冲产量（"抢钱模式"），还是产能过剩要压成本（"生存模式"），都要点出对应
   的可执行改进方向。

## 微观层（面向工艺优化与预测性维护）
1. 若数据里能看出生产阶段划分（如阶段状态类字段），按阶段拆解各阶段的时间、能耗与核心工艺参数
   表现，阶段0不纳入统计；若数据没有明确阶段划分，按运行/非运行时段拆分即可，不要臆造阶段。
2. 对每个核心参数，基于其均值/极差/波动趋势判断是否存在超出正常范围或波动明显异常的情况
   （不要编造具体的CPK数值或规格上下限，只做定性判断）。
3. 出现超差或异常波动时，给出可能的异常根因方向，以及具体的排查、保养或调整建议。

## 综合结论
结合宏观层与微观层，对该设备当前的整体运行状态给出一句话结论，并列出优先级最高的1-3条改进建议。

注意：
- 基于实际提供的数据进行分析，不要无中生有、不要编造未提供的具体数值
- 数据量不足的参数或时段，请明确注明数据有限
- 使用专业但易懂的语言"""


def get_analysis_system_prompt(analyze_running_only: bool) -> str:
    if analyze_running_only:
        return _MACRO_MICRO_FRAMEWORK
    return _MACRO_MICRO_FRAMEWORK + "\n\n补充要求：本次数据覆盖运行和非运行状态，微观层的参数分析请同时对比运行/非运行状态下的差异。"


def get_llm():
    return get_llm_client(async_client=True, timeout=300.0)


def _compute_utilization_summary(running_periods: List[Dict], time_range: Dict) -> Optional[str]:
    """用运行时段 + 分析窗口算一个"真实资产利用率"参考值，喂给宏观层当基准，
    避免让 LLM 自己口算一串时段的运行时长占比。"""
    try:
        win_start = datetime.strptime(time_range["start_time"], "%Y-%m-%d %H:%M:%S")
        win_end = datetime.strptime(time_range["end_time"], "%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError, TypeError):
        return None
    total_seconds = (win_end - win_start).total_seconds()
    if total_seconds <= 0:
        return None

    running_seconds = 0.0
    for p in running_periods or []:
        try:
            p_start = datetime.strptime(p["start_time"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError, TypeError):
            continue
        end_raw = p.get("end_time")
        p_end = datetime.strptime(end_raw, "%Y-%m-%d %H:%M:%S") if end_raw else win_end
        seg_start, seg_end = max(p_start, win_start), min(p_end, win_end)
        if seg_end > seg_start:
            running_seconds += (seg_end - seg_start).total_seconds()

    idle_seconds = total_seconds - running_seconds
    utilization = running_seconds / total_seconds * 100
    return (
        f"分析时段共 {total_seconds / 3600:.1f} 小时，其中节拍内（运行）时长合计 "
        f"{running_seconds / 3600:.1f} 小时，节拍外（非运行）时长合计 "
        f"{idle_seconds / 3600:.1f} 小时，真实资产利用率 ≈ {utilization:.1f}%"
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
    """压缩参数数据为结构化文本：只传波动最大的前 8 个参数，保留每小时原始值。"""
    series = compressed.get("series", {})
    if not series:
        return "  (无参数数据)"

    # 按波动程度排序，只传有实质变化的参数
    scored = []
    for pname, buckets in series.items():
        vals = [b['avg'] for b in buckets if b['avg'] is not None]
        if len(vals) < 2:
            continue
        mean_val = sum(vals) / len(vals)
        rng = max(vals) - min(vals)
        # 极差 < 均值 1% 的可视为无变化，跳过
        if mean_val != 0 and rng / abs(mean_val) < 0.01:
            continue
        score = rng / (abs(mean_val) + 0.001)
        scored.append((score, pname))
    scored.sort(reverse=True)
    top_params = {p for _, p in scored[:8]}

    parts = [f"数据时间范围: {compressed.get('start_time')} ~ {compressed.get('end_time')}（共{compressed.get('total_hours', 0):.1f}小时）"]
    parts.append(f"参数数量: {len(series)}（以下仅展示波动最大的 {len(top_params)} 个）")
    parts.append("")

    for pname in sorted(top_params):
        buckets = series[pname]
        parts.append(f"--- {pname} ---")
        for b in buckets:
            parts.append(
                f"  [{b['hour']}] "
                f"avg={b['avg']} min={b['min']} max={b['max']} "
                f"std={b['std']} count={b['count']}"
            )
        parts.append("")

    return "\n".join(parts)


async def _query_knowledge_base_async(device_name: str, params_summary: str) -> Optional[str]:
    """异步查询知识库，在线程池中跑同步 RAGFlow 调用，不阻塞事件循环。"""
    def _do_query():
        return _query_knowledge_base_sync(device_name, params_summary)
    loop = __import__('asyncio').get_event_loop()
    return await loop.run_in_executor(_kb_executor, _do_query)


import threading as _threading
import time as _time

_KB_CACHE: Dict[tuple, tuple] = {}            # (device_name, question) -> (expire_ts, answer)
_KB_INFLIGHT: Dict[tuple, Any] = {}           # (device_name, question) -> Event，正在查询中
_KB_CACHE_LOCK = _threading.Lock()
_KB_CACHE_TTL = 3600.0                         # 工艺文档不会分钟级变化，1 小时足够
_KB_CACHE_MAX = 256
_KB_WAIT_TIMEOUT = 120.0


def query_knowledge_base(device_name: str, question: str) -> Optional[str]:
    """带缓存 + single-flight 的知识库检索。

    为什么要缓存：一次 KPI 分析里 `_kpi_ai_insight` 会被调用 (型号数+1) 次，
    而它问的问题是**硬编码常量**，每次检索结果必然相同；阶段分析则每阶段问一次。

    为什么还要 single-flight：这些调用现在是并发发出的，光有缓存会被击穿 ——
    N 个请求同时未命中、同时去打 RAGFlow，缓存等于没起作用。这里让同一 key 只放
    一个请求真正出去，其余等它的结果。
    """
    key = (device_name or "", question or "")
    now = _time.monotonic()

    with _KB_CACHE_LOCK:
        hit = _KB_CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]
        ev = _KB_INFLIGHT.get(key)
        leader = ev is None
        if leader:
            ev = _threading.Event()
            _KB_INFLIGHT[key] = ev

    if not leader:                             # 跟随者：等 leader 查回来直接用
        ev.wait(timeout=_KB_WAIT_TIMEOUT)
        with _KB_CACHE_LOCK:
            hit = _KB_CACHE.get(key)
        return hit[1] if hit else None

    answer = None
    try:
        answer = _query_knowledge_base_sync(device_name, question)
    except Exception as e:
        print(f"[知识库] 检索失败 device={device_name}: {e}")
    finally:
        # 必须无条件唤醒等待者并清掉 inflight，否则一次异常会让后续同 key 的
        # 请求全部卡在 ev.wait() 上直到超时
        with _KB_CACHE_LOCK:
            if len(_KB_CACHE) >= _KB_CACHE_MAX:    # 容量控制：先清过期，仍超限则整体清空
                for k in [k for k, v in _KB_CACHE.items() if v[0] <= now]:
                    _KB_CACHE.pop(k, None)
                if len(_KB_CACHE) >= _KB_CACHE_MAX:
                    _KB_CACHE.clear()
            _KB_CACHE[key] = (now + _KB_CACHE_TTL, answer)
            _KB_INFLIGHT.pop(key, None)
        ev.set()
    return answer


def _query_knowledge_base_sync(device_name: str, params_summary: str) -> Optional[str]:
    """从知识库（RAGFlow）检索设备工艺文档，作为 LLM 分析的参考上下文。"""
    chat_id = os.getenv("DEVICE_PARAM_KB_CHAT_ID") or os.getenv("RAGFLOW_DOC_ASSISTANT_ID")
    if not chat_id:
        return None
    try:
        try:
            from backend.services.agentic_qa.ragflow.client import RAGFlowClient
        except ImportError:
            from services.agentic_qa.ragflow.client import RAGFlowClient

        client = RAGFlowClient()
        client.chat_id = chat_id
        question = (
            f"请提供 {device_name} 设备的以下分析参考资料：\n"
            f"1. 该设备的工艺参数标准范围和正常波动区间\n"
            f"2. 关键参数的常见异常模式及对应根因\n"
            f"3. 类似的参数趋势变化案例和排查建议\n\n"
            f"当前数据特征摘要：{params_summary[:500]}"
        )
        result = client.chat_sync(question)
        if result.get("success") and result.get("answer"):
            answer = result["answer"]
            # KB 结果超过 2500 字时，用小 LLM 压缩保留原意
            if len(answer) > 2500:
                try:
                    import asyncio
                    async def _compress():
                        llm = get_llm()
                        resp = await llm.chat.completions.create(
                            model=CONFIG["model"],
                            messages=[{
                                "role": "system",
                                "content": "请将以下知识库检索结果压缩为简洁的要点摘要，保留关键数据、标准范围和异常排查建议，不丢失任何可引用的具体数值和判断依据。"
                            }, {
                                "role": "user",
                                "content": answer
                            }],
                            temperature=0.1,
                            max_tokens=1200,
                        )
                        return resp.choices[0].message.content
                    answer = asyncio.run(_compress())
                except Exception as e:
                    print(f"[AI分析] KB 压缩失败，使用前 2500 字: {e}")
                    answer = answer[:2500] + "...(已截断)"
            return answer
    except Exception as e:
        print(f"[AI分析] 知识库查询失败（不影响分析）: {e}")
    return None


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
    utilization_text = _compute_utilization_summary(running_periods, time_range) or "  数据不足，无法计算资产利用率"

    # 知识库增强：异步检索设备工艺文档（与 LLM 调用可并行）
    kb_text = await _query_knowledge_base_async(device_name, data_text[:800])
    kb_section = ""
    if kb_text:
        kb_section = f"\n\n## 知识库参考（来自设备工艺文档，请在分析时参考以下内容）\n{kb_text}\n"

    if analyze_running_only:
        user_prompt = """## 设备信息
- 设备编号: {}
- 设备名称: {}
- 分析时间范围: {} ~ {}
- 分析模式: 仅分析运行状态数据

## 时间切分与资产利用率参考（已按运行时段计算，宏观层直接引用，不需要你重新口算）
{}

## 运行时段
{}

## 压缩后的参数数据（按小时聚合）
{}{}

请严格按系统提示的"宏观层 / 微观层 / 综合结论"框架输出分析。""".format(device_code, device_name or device_code, time_range.get('start_time'), time_range.get('end_time'), utilization_text, periods_text, data_text, kb_section)
    else:
        user_prompt = """## 设备信息
- 设备编号: {}
- 设备名称: {}
- 分析时间范围: {} ~ {}
- 分析模式: 分析全部数据（包括运行和非运行状态）

## 时间切分与资产利用率参考（已按运行时段计算，宏观层直接引用，不需要你重新口算）
{}

## 运行时段
{}

## 压缩后的参数数据（按小时聚合）
{}

 请严格按系统提示的"宏观层 / 微观层 / 综合结论"框架输出分析，微观层请特别对比运行与非运行状态下的参数差异。""".format(device_code, device_name or device_code, time_range.get('start_time'), time_range.get('end_time'), utilization_text, periods_text, data_text, kb_section)

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


async def screen_params(
    device_code: str,
    device_name: str,
    conn,
    days: int = 7,
) -> Dict[str, Any]:
    """Step ① 参数筛选：两阶段流水线。

    Phase 1（秒级）：拉数据 → Python 算统计 → 启发式粗筛
    Phase 2（可选）：LLM 增强分类，失败不影响结果

    结果覆盖该设备定义的全部参数（来自 dev_device_param），不会因为某个参数在
    最近 days 天窗口内没有数据就把它从列表里漏掉：近窗口无数据的参数会回退去
    拉取该参数自己最近一批历史数据用于分类（标记为 stale）；连历史数据都没有
    的参数也会以 nodata 分类原样返回，交给前端展示/人工勾选。
    """
    from datetime import timedelta
    from psycopg2.extras import RealDictCursor
    import statistics as stats_mod
    from .services import TimescaleDB
    from . import tuning

    # 阈值全部来自按设备的可调配置（未配置则用默认值），工艺可自助调整不必改代码
    tcfg = tuning.load(conn, device_code)

    end = datetime.now()
    start = end - timedelta(days=days)

    # 该设备定义的全部参数点位（含关联电表），不依赖是否有数据
    all_p_names: List[str] = []
    display_name_map: Dict[str, str] = {}
    meter_ids: List[str] = []
    try:
        _points_db = TimescaleDB()
        _points_db.conn = conn
        _points = _points_db.get_points(device_code)
        all_p_names = [p["p_name"] for p in _points]
        display_name_map = {p["p_name"]: p.get("display_name") or p["p_name"] for p in _points}
        meter_ids = _points_db.get_energy_device_ids(device_code)
    except Exception:
        all_p_names = []

    _ENERGY_WHITELIST = ("ene_eptotal", "ene_imp")

    # === Phase 1: 快速统计 + 启发式筛选（近 days 天窗口）===
    # 每参数公平采样(ROW_NUMBER PARTITION BY)：高频参数不会霸占全部 LIMIT 配额，
    # 低频参数(如设定值/残余量)也能拿到自己的全部数据点。同时取 point_time 供
    # 后续"同变参数"关联分析使用。
    _PER_PARAM_LIMIT = tcfg["screen_per_param_limit"]
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '30s'")
            alarm_select = """
                SELECT a.point_id AS p_name,
                       COALESCE(a.point_value_full, a.point_value)::double precision AS v,
                       a.point_time
                FROM device_alarm_info a
                WHERE a.device_id = %s
                  AND a.point_time >= %s AND a.point_time <= %s
                  AND a.point_value IS NOT NULL
            """
            selects = [alarm_select]
            params: list = [device_code, start, end]
            if meter_ids:
                selects.append("""
                    SELECT e.point_id AS p_name,
                           e.point_value::double precision AS v,
                           e.point_time
                    FROM device_energy_info e
                    WHERE e.device_id = ANY(%s)
                      AND e.point_time >= %s AND e.point_time <= %s
                      AND e.point_id = ANY(%s)
                      AND e.point_value IS NOT NULL
                """)
                params.extend([meter_ids, start, end, list(_ENERGY_WHITELIST)])
            union_sql = " UNION ALL ".join(f"({s})" for s in selects)
            cur.execute(f"""
                SELECT p_name, v, point_time FROM (
                    SELECT p_name, v, point_time,
                           ROW_NUMBER() OVER (PARTITION BY p_name ORDER BY point_time DESC) AS rn
                    FROM ({union_sql}) combined
                ) ranked
                WHERE rn <= %s
                ORDER BY p_name, point_time
            """, params + [_PER_PARAM_LIMIT])
            rows = cur.fetchall()
    except Exception as e:
        return {"error": f"查询失败: {e}", "step": 1}

    if not rows and not all_p_names:
        return {"error": "该设备在指定时间范围内无数据", "step": 1}

    # 按参数分组（同时保留时间戳，供关联分析）
    param_vals: Dict[str, List[float]] = {}
    param_times: Dict[str, List[Any]] = {}
    for r in rows:
        param_vals.setdefault(r["p_name"], []).append(r["v"])
        param_times.setdefault(r["p_name"], []).append(r["point_time"])

    # 近窗口没数据、但设备定义里有的参数：回退拉各自最近一批历史数据（不限定日期），
    # 避免"因为最近没数据就不显示"
    stale_last_seen: Dict[str, Any] = {}
    missing = [p for p in all_p_names if p not in param_vals]
    if missing:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET statement_timeout = '15s'")
                # 工艺点位
                cur.execute("""
                    SELECT p_name, v, point_time FROM (
                        SELECT a.point_id AS p_name,
                               COALESCE(a.point_value_full, a.point_value)::double precision AS v,
                               a.point_time,
                               ROW_NUMBER() OVER (PARTITION BY a.point_id ORDER BY a.point_time DESC) AS rn
                        FROM device_alarm_info a
                        WHERE a.device_id = %s AND a.point_id = ANY(%s) AND a.point_value IS NOT NULL
                    ) t
                    WHERE rn <= 500
                    ORDER BY point_time
                """, (device_code, missing))
                for r in cur.fetchall():
                    param_vals.setdefault(r["p_name"], []).append(r["v"])
                    prev = stale_last_seen.get(r["p_name"])
                    if prev is None or r["point_time"] > prev:
                        stale_last_seen[r["p_name"]] = r["point_time"]
                # 能耗点位（有关联电表时）
                if meter_ids:
                    energy_missing = [p for p in missing if p in _ENERGY_WHITELIST]
                    if energy_missing:
                        cur.execute("""
                            SELECT p_name, v, point_time FROM (
                                SELECT e.point_id AS p_name,
                                       e.point_value::double precision AS v,
                                       e.point_time,
                                       ROW_NUMBER() OVER (PARTITION BY e.point_id ORDER BY e.point_time DESC) AS rn
                                FROM device_energy_info e
                                WHERE e.device_id = ANY(%s) AND e.point_id = ANY(%s) AND e.point_value IS NOT NULL
                            ) t
                            WHERE rn <= 500
                            ORDER BY point_time
                        """, (meter_ids, energy_missing))
                        for r in cur.fetchall():
                            param_vals.setdefault(r["p_name"], []).append(r["v"])
                            prev = stale_last_seen.get(r["p_name"])
                            if prev is None or r["point_time"] > prev:
                                stale_last_seen[r["p_name"]] = r["point_time"]
        except Exception as e:
            # 历史数据回退失败不致命（这些参数会被标 nodata），但必须留痕，
            # 否则"某些参数莫名其妙没数据"永远查不出原因
            print(f"[参数筛选] 历史数据回退查询失败 device={device_code}: {e}")

    # 启发式规则（不调 LLM，纯 Python，秒级）
    # 分类规则：直白描述参数行为模式，不再用"经营管理"等抽象词
    HEURISTIC_RULES = [
        # (条件函数, 形态, 理由)
        # 数据不足必须排在最前且单独成类：样本太少时下面所有判断都不可靠。
        # 原来它被归成 constant("值完全不变")并因此自动取消勾选 ——
        # "我还不知道它变不变"被当成了"它确实不变"，是把未知冒充成已知。
        (lambda f: f["n"] < 10, "insufficient", "数据点不足(<10)，无法判断形态"),
        (lambda f: f["uniq"] <= 1, "constant", "值完全不变"),
        (lambda f: f["range_ratio"] < tcfg["flat_range_ratio"] and f["change_rate"] < 0.01,
         "constant", f"极差<{tcfg['flat_range_ratio']:.0%}且几乎不变"),
        (lambda f: f["directionality"] >= 0.5, "increasing", "持续递增"),
        (lambda f: f["directionality"] <= -0.5, "decreasing", "持续递减"),
    ]

    # 参数画像（ptype/category）：purpose 推断要用。没生成过画像也不影响，
    # 那时只靠形态 + 命名规则推断，置信度自然偏低，交给 Phase2 补。
    profile_map: Dict[str, Dict[str, Any]] = {}
    try:
        from . import param_profile as _pp
        for _prof in _pp.load_profiles(conn, device_code):
            if _prof.get("p_name"):
                profile_map[_prof["p_name"]] = _prof
    except Exception as e:
        print(f"[参数筛选] 读取参数画像失败（purpose 将只按命名推断）: {e}")

    classified = []
    for p_name, vals in param_vals.items():
        n = len(vals)
        uniq = len(set(round(v, 2) for v in vals))
        vmin, vmax = min(vals), max(vals)
        mean_val = sum(vals) / n
        std_val = stats_mod.stdev(vals) if n >= 2 else 0
        rng_ratio = (vmax - vmin) / (abs(mean_val) + 0.001) if mean_val != 0 else 0
        changes = sum(1 for i in range(1, n) if vals[i] != vals[i-1])
        change_rate = changes / (n - 1) if n > 1 else 0
        # 方向占比：判断递增/递减/波动。
        # 用"净漂移/总波动"而非"上涨步数占比"：带批次升降(0→800再回落)的实时重量
        # 即使上涨步数略多，净漂移也接近0，不会被误判为持续递增。
        inc_steps = sum(1 for i in range(1, n) if vals[i] > vals[i-1])
        dec_steps = sum(1 for i in range(1, n) if vals[i] < vals[i-1])
        _dir_total = inc_steps + dec_steps
        inc_ratio = inc_steps / _dir_total if _dir_total > 0 else 0
        dec_ratio = dec_steps / _dir_total if _dir_total > 0 else 0
        _total_var = sum(abs(vals[i] - vals[i-1]) for i in range(1, n))
        directionality = (vals[-1] - vals[0]) / _total_var if _total_var > 0 else 0
        trend = 0.0
        if n > 10 and std_val > 0:
            xm = (n - 1) / 2; ym = mean_val
            num = sum((i - xm) * (vals[i] - ym) for i in range(n))
            den = sum((i - xm) ** 2 for i in range(n))
            if den > 0:
                trend = num / den * n / (abs(mean_val) + 0.001)

        f = {"n": n, "uniq": uniq, "range_ratio": rng_ratio,
             "change_rate": change_rate, "trend": trend,
             "inc_ratio": inc_ratio, "dec_ratio": dec_ratio,
             "directionality": directionality}

        # 脉冲型检测：阶梯状 + 循环规律 + 周期往复（三大特征）
        # 只对疑似阶梯参数(平坦率>50%、离散值少)做深度分析，避免连续参数浪费算力
        cat, reason = "fluctuating", "上下波动"
        flat_ratio = 1 - change_rate
        pulse_detected = False
        if n >= tcfg["pulse_min_points"] and 1 < uniq <= 100 and flat_ratio > 0.5:
            _times = param_times.get(p_name, [])
            if _times and len(_times) == n:
                _pf = _analyze_pulse_features(vals, _times)
                if (_pf and _pf["step_score"] > tcfg["pulse_step_score"]
                        and _pf.get("cycle_score", 0) > tcfg["pulse_cycle_score"]):
                    cat = "pulse"
                    _parts = []
                    if _pf.get("pattern_match_rate", 0) >= 0.6:
                        _parts.append(f"循环匹配{_pf['pattern_match_rate']:.0%}")
                    if _pf.get("cycle_minutes"):
                        _parts.append(f"周期≈{_pf['cycle_minutes']}分钟")
                    reason = f"脉冲型：阶梯循环" + (f"（{'，'.join(_parts)}）" if _parts else "")
                    pulse_detected = True

        if not pulse_detected:
            for rule_fn, rule_cat, rule_reason in HEURISTIC_RULES:
                if rule_fn(f):
                    cat, reason = rule_cat, rule_reason
                    break

        is_stale = p_name in stale_last_seen
        if is_stale:
            reason = f"最近{days}天无数据，用历史数据判断({reason})"

        classified.append({
            "p_name": p_name,
            # shape 是新名字（形态）；category 保留同值，兼容已保存的筛选状态和旧前端
            "shape": cat,
            "category": cat,
            "reason": reason,
            # insufficient 默认不勾选，但它和 constant 的含义不同：前者是"还不知道"，
            # 前端会单独标出来提示补数据后再看
            "checked": cat not in ("constant", "nodata", "insufficient"),
            "n": n, "uniq": uniq,
            "vmin": round(vmin, 2), "vmax": round(vmax, 2),
            "mean": round(mean_val, 2), "std": round(std_val, 2),
            "range_ratio": round(rng_ratio, 4),
            "change_rate": round(change_rate, 4),
            "trend": round(trend, 4),
            "stale": is_stale,
            "last_seen": stale_last_seen[p_name].isoformat() if is_stale else None,
        })

    # 定义里有、但连历史数据都没有的参数：原样返回，标 nodata，交给前端展示/人工勾选
    for p_name in all_p_names:
        if p_name not in param_vals:
            classified.append({
                "p_name": p_name,
                "shape": "nodata",
                "category": "nodata",
                "reason": "无历史数据",
                "checked": False,
                "n": 0, "uniq": 0,
                "vmin": None, "vmax": None, "mean": None, "std": None,
                "range_ratio": 0, "change_rate": 0, "trend": 0,
                "stale": False, "last_seen": None,
            })

    classified.sort(key=lambda x: (x["category"] in ("constant", "nodata"), -x["range_ratio"]))

    # === 同变参数分组：检测哪些参数在相近时刻一起变化（如配方/批次切换时一组设定值同时刷新）===
    # 方法：提取每个参数值变化的时刻(按 10 秒桶取整)，两两计算 Jaccard 相似度
    # (交集/并集)。Jaccard 天然惩罚不对称：几乎不变的参数(仅2-3次跳变)即使碰巧
    # 对上活跃参数的时刻，相似度也很低，不会被误归同组。另要求每方至少 4 次跳变。
    # 相似度≥0.8 才判为"同步变化"，并在输出里附上每对的相似度分数。
    co_change_groups: Dict[str, List[str]] = {}
    co_change_scores: Dict[str, Dict[str, float]] = {}
    try:
        from collections import defaultdict as _dd
        _TRANSITION_BUCKET_SEC = tcfg["co_change_bucket_sec"]
        _MIN_TRANSITIONS = tcfg["co_change_min_transitions"]
        _JACCARD_THRESHOLD = tcfg["co_change_jaccard"]
        param_transitions: Dict[str, set] = {}
        for p_name, times in param_times.items():
            vals = param_vals[p_name]
            if len(vals) < 2:
                continue
            buckets = set()
            for i in range(1, len(vals)):
                if vals[i] != vals[i - 1]:
                    buckets.add(int(times[i].timestamp() / _TRANSITION_BUCKET_SEC))
            if len(buckets) >= _MIN_TRANSITIONS:
                param_transitions[p_name] = buckets

        _adj = _dd(set)
        _sim: Dict[tuple, float] = {}
        _pn = list(param_transitions.keys())
        for i in range(len(_pn)):
            for j in range(i + 1, len(_pn)):
                a, b = _pn[i], _pn[j]
                ta, tb = param_transitions[a], param_transitions[b]
                overlap = len(ta & tb)
                union = len(ta | tb)
                if union > 0:
                    sim = overlap / union
                    if sim >= _JACCARD_THRESHOLD:
                        _adj[a].add(b)
                        _adj[b].add(a)
                        _sim[(a, b)] = round(sim, 3)

        _visited: set = set()
        for p in _pn:
            if p in _visited or p not in _adj:
                continue
            comp: set = set()
            queue = [p]
            while queue:
                node = queue.pop()
                if node in _visited:
                    continue
                _visited.add(node)
                comp.add(node)
                queue.extend(n for n in _adj[node] if n not in _visited)
            if len(comp) >= 2:
                members = sorted(comp)
                for m in members:
                    peers = [x for x in members if x != m]
                    co_change_groups[m] = peers
                    scores = {}
                    for x in peers:
                        key = (m, x) if m < x else (x, m)
                        scores[x] = _sim.get(key, 0.0)
                    co_change_scores[m] = scores

        # 把同变信息追加到 classified 的 reason 里（用中文名 + 相似度分数）
        group_label_map = {}  # p_name -> 简短标签
        for p_name, peers in co_change_groups.items():
            peer_labels = [
                f"{display_name_map.get(x, x)}({co_change_scores[p_name].get(x, 0):.0%})"
                for x in peers[:4]
            ]
            short = ", ".join(peer_labels) + ("…" if len(peers) > 4 else "")
            group_label_map[p_name] = f"与 {short} 同步变化"
        for c in classified:
            label = group_label_map.get(c["p_name"])
            if label:
                c["co_change"] = co_change_groups[c["p_name"]]
                c["co_change_scores"] = co_change_scores[c["p_name"]]
                c["reason"] = f"{c['reason']}；{label}"
            else:
                c["co_change"] = []
    except Exception as e:
        print(f"[参数筛选] 同变参数分组失败 device={device_code}: {e}")
        for c in classified:
            c.setdefault("co_change", [])
            c.setdefault("co_change_scores", {})

    # === 用途推断 ===
    # 放在同变分组之后：配方设定值的判据之一就是"跟着一组参数同时跳变"。
    # 人工设定 > 画像已确认 > 规则推断 —— 人的判断永远不被自动结果覆盖，
    # 否则工艺改一次、重新筛选一次就被冲掉，没人会再愿意维护它。
    saved_manual: Dict[str, str] = {}
    try:
        _saved = load_screen_state(conn, device_code) or {}
        for _c in (_saved.get("classified") or []):
            if _c.get("purpose_confidence") == "manual" and _c.get("purpose") in VALID_PURPOSES:
                saved_manual[_c.get("p_name")] = _c["purpose"]
    except Exception as e:
        print(f"[参数筛选] 读取已保存用途失败（将全部按规则推断）: {e}")

    for c in classified:
        pn = c["p_name"]
        prof = profile_map.get(pn) or {}
        if pn in saved_manual:
            c["purpose"] = saved_manual[pn]
            c["purpose_label"] = PURPOSE_LABELS[saved_manual[pn]]
            c["purpose_reason"] = "人工设定"
            c["purpose_confidence"] = "manual"
            continue
        confirmed_purpose = prof.get("purpose") if prof.get("confirmed") else None
        if confirmed_purpose in VALID_PURPOSES:
            c["purpose"] = confirmed_purpose
            c["purpose_label"] = PURPOSE_LABELS[confirmed_purpose]
            c["purpose_reason"] = "工艺已确认"
            c["purpose_confidence"] = "confirmed"
            continue
        purpose, why, conf = _infer_purpose(
            pn, display_name_map.get(pn, ""), c["shape"], prof, bool(c.get("co_change")))
        c["purpose"] = purpose
        c["purpose_label"] = PURPOSE_LABELS[purpose]
        c["purpose_reason"] = why
        c["purpose_confidence"] = conf

    result = {
        "step": 1, "days": days,
        "classified": classified,
        "summary": _make_summary(classified),
        "purpose_summary": _make_purpose_summary(classified),
        "sample_info": f"每参数≤{_PER_PARAM_LIMIT}点 · 最近{days}天",
        # 形态分类**永远**由启发式决定，LLM 不参与 —— 它只看得到聚合统计，
        # 反复把噪声读成趋势。这个字段如实反映形态的来源。
        "shape_source": "heuristic",
        "purpose_source": "rules",
    }

    # === Phase 2: LLM 推断用途（只处理规则判不准的参数） ===
    # 原来这里让 LLM 往 reason 里追加一句装饰性文案，还把 source 标成 "ai"，
    # 让前端显示"AI 分类"——付出了成本和延迟，产出只是文案，还给了错误印象。
    # 现在它干一件真正需要工艺知识、规则做不到的事：判断这个参数是用来干什么的。
    # 形态分类依旧禁止 LLM 改动。
    undecided = [c for c in classified
                 if c.get("purpose_confidence") == "low" and c["shape"] not in ("nodata", "insufficient")]
    if undecided:
        try:
            listing = "\n".join(
                f"- {c['p_name']}（{display_name_map.get(c['p_name'], c['p_name'])}）："
                f"形态={c['shape']}，均值={c['mean']}，极差比={c['range_ratio']}，"
                f"当前推测={c['purpose']}"
                for c in undecided[:30]
            )
            kb = await _query_knowledge_base_async(device_name, listing[:600])
            options = "、".join(f"{k}({v})" for k, v in PURPOSE_LABELS.items())
            prompt = f"""设备：{device_name}。下面这些参数的**用途**用规则判断不准，请你结合工艺知识判断。

可选用途只有这几个：{options}

判断依据：
- pace：标记生产阶段/循环节拍的信号
- quality：需要盯规格上下限、做 SPC/CPK 的工艺量
- output：产量、物料重量、计数
- energy：电能/能耗计量
- recipe：配方设定值，换产品时整组变化，本身不算异常
- health：反映设备劣化的量（振动、电流、温升等）
- ignore：与分析无关

参数列表：
{listing}
{("知识库参考：" + kb[:400]) if kb else ""}

只返回JSON，不要解释：{{"items":[{{"p_name":"...","purpose":"上面7个之一","why":"不超过15字的理由"}}]}}"""
            llm = get_llm()
            resp = await llm.chat.completions.create(
                model=CONFIG["model"], messages=[{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=900,
            )
            import re
            m = re.search(r'\{[\s\S]*\}', resp.choices[0].message.content or "")
            applied = 0
            if m:
                by_name = {c["p_name"]: c for c in undecided}
                for item in json.loads(m.group()).get("items", []):
                    c = by_name.get(item.get("p_name"))
                    pv = item.get("purpose")
                    # 只接受合法取值，LLM 编出来的新类别一律丢弃
                    if c is None or pv not in VALID_PURPOSES:
                        continue
                    c["purpose"] = pv
                    c["purpose_label"] = PURPOSE_LABELS[pv]
                    c["purpose_reason"] = (item.get("why") or "AI 结合工艺知识判断")[:30]
                    c["purpose_confidence"] = "ai"
                    applied += 1
            if applied:
                result["purpose_source"] = "rules+ai"
                result["purpose_ai_count"] = applied
                result["purpose_summary"] = _make_purpose_summary(classified)
        except Exception as e:
            # 用途推断失败不影响筛选结果（规则给的初值仍在），但要留痕
            print(f"[参数筛选] LLM 用途推断失败 device={device_code}: {e}")

    return result


# ══════════════════════════════════════════════════════════
# 参数的四个正交维度
#
#   shape    形态   —— 波形长什么样（本模块启发式判定，全自动）
#                      决定：能不能当脉搏、要不要算漂移、用什么图
#   ptype    信号类型 —— switch/state/counter/setpoint/continuous（param_profile 判定）
#                      决定：能不能做 CPK、是不是累计量
#   category 物理量 —— temperature/weight/power/...（param_profile 判定）
#                      决定：单位、聚合方式
#   purpose  用途   —— 归谁管、报表归口、告警路由（规则建议 + 人工确认）
#
# 前三个都是"这个信号是什么"，只有 purpose 回答"拿它干什么"。
# 精益上指标必须能驱动行动："这是波动类参数"不指向任何动作，
# "这是质量管控参数"才指向质量工程师和 SPC 告警。
# ══════════════════════════════════════════════════════════

PURPOSE_LABELS = {
    "pace": "节拍基准",
    "quality": "质量管控",
    "output": "产量计量",
    "energy": "能耗计量",
    "recipe": "配方设定",
    "health": "设备健康",
    "ignore": "不纳入分析",
}
VALID_PURPOSES = set(PURPOSE_LABELS)

_ENERGY_PREFIXES = ("ene_", "energy_", "kwh")
_HEALTH_KEYWORDS = ("振动", "轴承", "电流", "温升", "油压", "磨损")
_OUTPUT_KEYWORDS = ("重量", "称", "产量", "计数", "累计量", "料")


def _infer_purpose(p_name: str, display_name: str, shape: str,
                   prof: Optional[Dict[str, Any]], has_co_change: bool):
    """由 形态 + 信号类型 + 物理量 + 命名 推断用途。

    返回 (purpose, reason, confidence)。confidence='low' 的交给 Phase2 让 LLM 结合
    工艺知识判断 —— 那才是 LLM 在这里唯一有价值的活，比生成装饰性文案强得多。
    """
    prof = prof or {}
    ptype = prof.get("ptype") or ""
    category = prof.get("category") or ""
    is_stage = bool(prof.get("is_stage_param"))
    name = f"{p_name} {display_name or ''}".lower()
    cn = display_name or ""

    # 1) 能耗计量：命名前缀最可靠，其次是"功率类累计量"
    if any(name.startswith(x) or f" {x}" in name for x in _ENERGY_PREFIXES):
        return "energy", "能耗点位命名", "high"
    if category == "power" and ptype == "counter":
        return "energy", "功率类累计量", "high"

    # 2) 节拍基准：阶段码/状态机，是所有周期分析的锚点
    if is_stage or ptype == "state" or shape == "pulse":
        return "pace", "阶段码/脉冲型信号", "high"

    # 3) 产量计量：重量参数已被空跑判定实际使用
    if category == "weight" or any(k in cn for k in _OUTPUT_KEYWORDS):
        return "output", "物料重量/计数", "high"

    # 4) 配方设定：设定值，或"跟着一组参数同时跳变"的常量（换配方时整组刷新）
    if ptype == "setpoint":
        return "recipe", "设定值类型", "high"
    if has_co_change and shape in ("constant", "fluctuating"):
        return "recipe", "与其它参数同步跳变（疑似配方切换）", "medium"

    # 5) 设备健康：振动/电流/温升这类看劣化趋势的
    if any(k in cn for k in _HEALTH_KEYWORDS):
        return "health", "设备健康类命名", "medium"
    if category == "speed":
        return "health", "转速类", "low"

    # 6) 质量管控：连续工艺量，要做 SPC/CPK
    if category in ("temperature", "pressure", "vacuum", "flow", "level"):
        return "quality", f"连续工艺量({category})", "high"

    # 7) 没信息量的直接排除
    if shape in ("constant", "nodata", "insufficient"):
        return "ignore", "无变化/无数据，不纳入分析", "medium"

    # 8) 兜底：连续变化的量默认按质量管控看，但置信度低，交给 Phase2
    return "quality", "波动的连续量（待确认）", "low"


def _make_summary(classified):
    cats = {}
    for c in classified:
        cats[c["category"]] = cats.get(c["category"], 0) + 1
    return " · ".join(f"{k}{v}" for k, v in cats.items())


def _make_purpose_summary(classified):
    """按用途汇总，用中文标签 —— 这一行才是现场能直接看懂的分工视图。"""
    counts = {}
    for c in classified:
        p = c.get("purpose")
        if p:
            counts[p] = counts.get(p, 0) + 1
    order = list(PURPOSE_LABELS)
    return " · ".join(f"{PURPOSE_LABELS[k]}{counts[k]}" for k in order if counts.get(k))


# ── 筛选状态持久化 ──

def save_screen_state(conn, device_code: str, classified: list = None,
                      checked_params: list = None, workflow_step: int = 0,
                      pulse_param: str = None, state_data: dict = None) -> None:
    """保存设备参数筛选状态到数据库（部分更新语义）。

    传 None 的字段＝"本次不涉及，保留库里原值"；传空列表 [] 才是"明确清空"。
    这样效率/KPI 等只关心 workflow_step 的调用方不会把「参数设定」页存的
    classified/checked_params 冲掉（曾导致筛选结果凭空消失）。
    """
    import json
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_param_screen_state (
                device_code    VARCHAR(64) PRIMARY KEY,
                classified     JSONB NOT NULL,
                checked_params TEXT[] NOT NULL DEFAULT '{}',
                workflow_step  INT NOT NULL DEFAULT 0,
                pulse_param    TEXT,
                state_data     JSONB,
                updated_at     TIMESTAMPTZ DEFAULT now()
            )
        """)
        # 兼容旧表缺少列（IF NOT EXISTS 本身已幂等，不需要额外 try/except 兜底）
        cur.execute("ALTER TABLE device_param_screen_state ADD COLUMN IF NOT EXISTS pulse_param TEXT")
        cur.execute("ALTER TABLE device_param_screen_state ADD COLUMN IF NOT EXISTS state_data JSONB")
        cur.execute("""
            INSERT INTO device_param_screen_state (device_code, classified, checked_params, workflow_step, pulse_param, state_data, updated_at)
            VALUES (
                %(device_code)s,
                COALESCE(%(classified)s::jsonb, '[]'::jsonb),
                COALESCE(%(checked_params)s::text[], '{}'::text[]),
                %(workflow_step)s,
                %(pulse_param)s,
                %(state_data)s::jsonb,
                now()
            )
            ON CONFLICT (device_code) DO UPDATE SET
                classified = COALESCE(%(classified)s::jsonb, device_param_screen_state.classified),
                checked_params = COALESCE(%(checked_params)s::text[], device_param_screen_state.checked_params),
                workflow_step = %(workflow_step)s,
                pulse_param = COALESCE(%(pulse_param)s, device_param_screen_state.pulse_param),
                state_data = COALESCE(%(state_data)s::jsonb, device_param_screen_state.state_data),
                updated_at = now()
        """, {
            "device_code": device_code,
            "classified": json.dumps(classified) if classified is not None else None,
            "checked_params": checked_params,
            "workflow_step": workflow_step,
            "pulse_param": pulse_param,
            "state_data": json.dumps(state_data) if state_data else None,
        })
    conn.commit()


def load_screen_state(conn, device_code: str) -> Optional[Dict[str, Any]]:
    """从数据库加载设备筛选状态。"""
    import json
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS device_param_screen_state (
                device_code VARCHAR(64) PRIMARY KEY,
                classified JSONB NOT NULL,
                checked_params TEXT[] NOT NULL DEFAULT '{}',
                workflow_step INT NOT NULL DEFAULT 0,
                pulse_param TEXT,
                state_data JSONB,
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        cur.execute(
            "SELECT * FROM device_param_screen_state WHERE device_code = %s",
            (device_code,))
        row = cur.fetchone()
    if not row:
        return None
    classified = row["classified"]
    if isinstance(classified, str):
        classified = json.loads(classified)
    state_data = row.get("state_data")
    if isinstance(state_data, str):
        state_data = json.loads(state_data)
    checked = row["checked_params"] or []
    return {
        "classified": classified,
        "checked_params": checked,
        "workflow_step": row["workflow_step"],
        "pulse_param": row.get("pulse_param"),
        "state_data": state_data,
        "updated_at": str(row["updated_at"]) if row.get("updated_at") else None,
    }


def discover_pulse_params(conn, device_code: str, device_name: str,
                          days: int = 7) -> Dict[str, Any]:
    """Step ② 脉搏发现：基于两大特征推荐最适合做 cycle 划分的参数。

    特征①阶梯状：参数值长时间保持不变、偶尔跳跃式切换（离散状态码）。
    特征②循环规律：跳转序列存在重复模式，周期时长稳定。

    典型脉搏参数（如 Tec_Stage）同时满足两条；连续振荡参数仅有循环性、
    无阶梯性，得分较低但仍可作为候选。
    """
    from datetime import timedelta
    from psycopg2.extras import RealDictCursor
    import statistics as st
    from .services import TimescaleDB

    end = datetime.now()
    start = end - timedelta(days=days)

    # 参数定义 + 关联电表 + 中文名
    display_name_map: Dict[str, str] = {}
    meter_ids: List[str] = []
    try:
        _pdb = TimescaleDB()
        _pdb.conn = conn
        _points = _pdb.get_points(device_code)
        display_name_map = {p["p_name"]: p.get("display_name") or p["p_name"] for p in _points}
        meter_ids = _pdb.get_energy_device_ids(device_code)
    except Exception as e:
        # 拿不到点位元数据只影响显示名/能耗点位，不阻断脉搏发现，但要留痕
        print(f"[脉搏发现] 读取点位元数据失败 device={device_code}: {e}")

    _ENERGY_WHITELIST = ("ene_eptotal", "ene_imp")
    _PER_PARAM_LIMIT = 10000

    # 每参数公平采样（含时间戳，供周期分析）
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '30s'")
            alarm_select = """
                SELECT a.point_id AS p_name,
                       COALESCE(a.point_value_full, a.point_value)::double precision AS v,
                       a.point_time
                FROM device_alarm_info a
                WHERE a.device_id = %s
                  AND a.point_time >= %s AND a.point_time <= %s
                  AND a.point_value IS NOT NULL
            """
            selects = [alarm_select]
            params: list = [device_code, start, end]
            if meter_ids:
                selects.append("""
                    SELECT e.point_id AS p_name,
                           e.point_value::double precision AS v,
                           e.point_time
                    FROM device_energy_info e
                    WHERE e.device_id = ANY(%s)
                      AND e.point_time >= %s AND e.point_time <= %s
                      AND e.point_id = ANY(%s)
                      AND e.point_value IS NOT NULL
                """)
                params.extend([meter_ids, start, end, list(_ENERGY_WHITELIST)])
            union_sql = " UNION ALL ".join(f"({s})" for s in selects)
            cur.execute(f"""
                SELECT p_name, v, point_time FROM (
                    SELECT p_name, v, point_time,
                           ROW_NUMBER() OVER (PARTITION BY p_name ORDER BY point_time DESC) AS rn
                    FROM ({union_sql}) combined
                ) ranked
                WHERE rn <= %s
                ORDER BY p_name, point_time
            """, params + [_PER_PARAM_LIMIT])
            rows = cur.fetchall()
    except Exception as e:
        return {"error": f"查询失败: {e}", "step": 2}

    if not rows:
        return {"error": "无数据", "step": 2}

    param_vals: Dict[str, List[float]] = {}
    param_times: Dict[str, List[Any]] = {}
    for r in rows:
        param_vals.setdefault(r["p_name"], []).append(r["v"])
        param_times.setdefault(r["p_name"], []).append(r["point_time"])

    candidates = []
    for p_name, vals in param_vals.items():
        if len(vals) < 50:
            continue
        feat = _analyze_pulse_features(vals, param_times[p_name])
        if feat:
            feat["p_name"] = p_name
            feat["display_name"] = display_name_map.get(p_name, p_name)
            candidates.append(feat)

    candidates.sort(key=lambda x: -x["score"])

    # KB 增强
    kb_text = None
    try:
        summary = ", ".join(
            f"{display_name_map.get(c['p_name'], c['p_name'])}({c['score']:.0f}分,周期{c.get('cycle_minutes')}min)"
            for c in candidates[:8]
        )
        kb_text = query_knowledge_base(device_name, f"该设备的生产节拍/阶段参数是什么？{summary}")
    except Exception as e:
        print(f"[脉搏发现] 知识库检索失败（改用纯统计排序） device={device_code}: {e}")

    kb_ranked = _kb_rerank_pulse_candidates(device_name, candidates[:10], kb_text) if kb_text else None
    if kb_ranked:
        rank_of = {p: i for i, p in enumerate(kb_ranked)}
        candidates.sort(key=lambda c: (rank_of.get(c["p_name"], len(kb_ranked)), -c["score"]))
        for c in candidates:
            if c["p_name"] in rank_of:
                c["reason"] = "知识库推荐：" + c["reason"]

    return {
        "step": 2, "days": days,
        "candidates": candidates[:20],
        "kb_hint": kb_text[:500] if kb_text else None,
        "kb_driven": bool(kb_ranked),
        "sample_info": f"每参数≤{_PER_PARAM_LIMIT}点 · 最近{days}天",
    }


def _analyze_pulse_features(vals: List[float], times: List[Any]) -> Optional[Dict[str, Any]]:
    """分析参数的两大脉搏特征：阶梯状(step) + 循环规律(cyclic)，返回特征指标和综合得分。"""
    import statistics as st
    n = len(vals)
    uniq = len(set(round(v, 2) for v in vals))
    if uniq <= 1:
        return None  # 恒定值，不可能是脉搏

    changes = sum(1 for i in range(1, n) if vals[i] != vals[i - 1])
    flat_ratio = 1 - changes / (n - 1) if n > 1 else 0  # 越高=越阶梯(平坦段占比)

    # === 特征①：阶梯状 ===
    # 提取去重连续序列（如 12,12,13,13,14,14,1,1 → 12,13,14,1）
    dedup = [vals[0]]
    for v in vals[1:]:
        if v != dedup[-1]:
            dedup.append(v)

    # 离散值因子：2~50 种离散值得分最高；>50 逐步衰减（连续参数）
    uniq_factor = 1.0 if uniq <= 50 else max(0.2, 1 - (uniq - 50) / 200)
    step_score = flat_ratio * uniq_factor

    # === 特征②：循环规律 ===
    # 在去重序列里找最短重复模式
    seq = dedup
    seq_len = len(seq)
    pattern = None
    pattern_rate = 0.0
    if seq_len >= 10:
        for plen in range(3, min(50, seq_len // 3) + 1):
            pat = seq[:plen]
            total = matches = 0
            for i in range(0, seq_len - plen + 1, plen):
                total += 1
                if seq[i:i + plen] == pat:
                    matches += 1
            if total > 0:
                rate = matches / total
                if rate > pattern_rate:
                    pattern_rate = rate
                    pattern = pat
        if pattern_rate < 0.5:
            pattern_rate = 0.0
            pattern = None

    # 时间周期分析（用真实时间戳，不假设采样间隔）
    cycle_min = None
    cycle_cv = 1.0
    cycle_count = 0

    def _time_cycle(boundary_val):
        """以"回到 boundary_val"为周期边界，返回 (durations_min, filtered) """
        starts = [times[0]]
        for i in range(1, n):
            if vals[i] == boundary_val and vals[i - 1] != boundary_val:
                starts.append(times[i])
        durs = []
        for i in range(1, len(starts)):
            d = (starts[i] - starts[i - 1]).total_seconds() / 60
            if d > 0:
                durs.append(d)
        if len(durs) >= 4:
            sd = sorted(durs)
            q1, q3 = sd[len(sd) // 4], sd[3 * len(sd) // 4]
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            durs = [d for d in durs if lo <= d <= hi]
        return durs

    if pattern and pattern_rate >= 0.5:
        durs = _time_cycle(pattern[0])
        if len(durs) >= 2:
            dm = st.mean(durs)
            cycle_cv = st.stdev(durs) / dm if dm > 0 else 1.0
            cycle_min = round(dm, 1)
            cycle_count = len(durs)

    cycle_regularity = max(0, 1 - min(cycle_cv, 1.0))
    # 阶梯参数：模式匹配率 × 周期稳定性；需至少2个完整周期
    cycle_score = pattern_rate * cycle_regularity if cycle_count >= 2 else pattern_rate * 0.3

    # 连续参数兜底：若阶梯检测弱但参数有波动，用均值穿越法补一轮
    if cycle_score < 0.15 and n > 100:
        mean_val = sum(vals) / n
        std_val = st.stdev(vals) if n >= 2 else 0
        if std_val > 0:
            cross_t = [times[i] for i in range(1, n)
                       if (vals[i - 1] < mean_val <= vals[i]) or (vals[i - 1] > mean_val >= vals[i])]
            if len(cross_t) >= 6:
                cdurs = [(cross_t[i + 1] - cross_t[i]).total_seconds() / 60
                         for i in range(len(cross_t) - 1)]
                if len(cdurs) >= 4:
                    sd = sorted(cdurs)
                    q1, q3 = sd[len(sd) // 4], sd[3 * len(sd) // 4]
                    iqr = q3 - q1
                    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                    cdurs = [d for d in cdurs if lo <= d <= hi]
                if len(cdurs) >= 3:
                    cdm = st.mean(cdurs)
                    ccv = st.stdev(cdurs) / cdm if cdm > 0 else 1
                    cont = max(0, 1 - min(ccv, 1)) * 0.4  # 连续参数权重低
                    if cont > cycle_score:
                        cycle_score = cont
                        cycle_min = round(cdm * 2, 1)
                        cycle_count = len(cdurs)
                        cycle_cv = ccv

    # 综合得分：阶梯性(35%) + 循环性(65%)
    score = round((0.35 * step_score + 0.65 * cycle_score) * 100)

    if score < 5:
        return None

    # 生成中文说明
    reasons = []
    if step_score > 0.85:
        reasons.append(f"阶梯状明显(平坦{flat_ratio:.0%},{uniq}种离散值)")
    elif step_score > 0.5:
        reasons.append(f"呈阶梯状({uniq}种离散值)")
    if pattern_rate >= 0.8:
        reasons.append(f"循环规律极强(匹配{pattern_rate:.0%})")
    elif pattern_rate >= 0.5:
        reasons.append(f"有循环规律(匹配{pattern_rate:.0%})")
    if cycle_min and cycle_count >= 2:
        reasons.append(f"周期≈{cycle_min}分钟({cycle_count}轮)")
    if cycle_cv < 0.3:
        reasons.append("周期极稳定")
    elif cycle_cv < 0.6:
        reasons.append("周期较稳定")

    if not reasons:
        return None

    return {
        "score": score,
        "step_score": round(step_score, 3),
        "cycle_score": round(cycle_score, 3),
        "pattern_match_rate": round(pattern_rate, 3),
        "cycle_minutes": cycle_min,
        "cycle_count": cycle_count,
        "cycle_cv": round(cycle_cv, 3),
        "flat_ratio": round(flat_ratio, 3),
        "n": n,
        "uniq": uniq,
        "pattern": [int(x) if x == int(x) else round(x, 2) for x in pattern] if pattern else None,
        "reason": "；".join(reasons),
    }


def _kb_rerank_pulse_candidates(device_name: str, candidates: List[Dict[str, Any]],
                                kb_text: str) -> Optional[List[str]]:
    """把两大特征(阶梯状+循环规律)打分的候选交给 LLM+知识库做最终判断。

    LLM 收到的不是裸分数，而是具体的特征描述（阶梯平坦率、模式匹配率、
    周期分钟数），让它结合工艺知识判断哪个最像"生产节拍/阶段状态"参数。
    """
    import re
    import asyncio
    summary = "\n".join(
        f"{c.get('display_name', c['p_name'])}({c['p_name']}): "
        f"综合{c['score']:.0f}分, 阶梯{c.get('step_score', 0):.2f}, "
        f"循环匹配{c.get('pattern_match_rate', 0):.0%}, "
        f"周期{c.get('cycle_minutes')}min×{c.get('cycle_count', 0)}轮, "
        f"{c['reason']}"
        for c in candidates
    )
    try:
        async def _call():
            llm = get_llm()
            prompt = f"""设备{device_name}。知识库参考：{kb_text[:500]}

以下是按"阶梯状变化+循环规律"两大特征打分的脉搏候选参数：
{summary}

脉搏参数的核心特征：①值呈阶梯状跳变(离散状态码)，②跳转序列有重复模式且周期稳定。
请结合知识库描述的工艺，判断哪个最符合"生产节拍/阶段状态"参数。
只返回JSON：{{"ranked": ["p_name1","p_name2",...]}}（用 p_name 代码）。
知识库信息不足时返回{{"ranked": []}}，不要猜测。"""
            resp = await llm.chat.completions.create(
                model=CONFIG["model"], messages=[{"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=300,
            )
            return resp.choices[0].message.content
        raw = asyncio.run(_call())
        m = re.search(r'\{[\s\S]*\}', raw)
        if not m:
            return None
        ranked = json.loads(m.group()).get("ranked", [])
        valid_names = {c["p_name"] for c in candidates}
        ranked = [p for p in ranked if p in valid_names]
        return ranked or None
    except Exception:
        return None


_PULSE_CHUNK_LIMIT = 50000


def _fetch_pulse_chunked(conn, device_code: str, pulse_param: str,
                         start: datetime, end: datetime):
    """按班次分块拉脉搏数据，返回 (rows, truncated_chunks)。

    为什么要分块：原来是单次 `ORDER BY point_time LIMIT 50000`（升序），窗口内
    点数超限时**尾部整段被丢弃**，而利用率的分母仍按完整窗口算 —— 丢掉的时间
    被 _build_state_timeline 判成 offline，利用率被系统性低估，且 window_truncated
    只检测前段缺失，完全不会提示。UI 允许 30 天窗口，单参数平均快于 52 秒/点就会触发。

    分块后每块只覆盖一个班次（12 小时），5 万点相当于 0.86 秒/点的采样率，
    实际不可能触发；万一触发也只影响那一块，并通过 truncated_chunks 报出来。
    """
    from psycopg2.extras import RealDictCursor
    from .shift import shifts_in_range

    chunks = [(w.start, w.end, w.label) for w in shifts_in_range(start, end)]
    if not chunks:                       # 极短窗口落不到任何班次时退回整段
        chunks = [(start, end, "全窗口")]

    rows: List[Dict[str, Any]] = []
    truncated: List[str] = []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SET statement_timeout = '60s'")
        for c_start, c_end, label in chunks:
            cur.execute("""
                SELECT a.point_value::double precision AS v, a.point_time
                FROM device_alarm_info a
                WHERE a.device_id = %s AND a.point_id = %s
                  AND a.point_time >= %s AND a.point_time < %s
                  AND a.point_value IS NOT NULL
                ORDER BY a.point_time LIMIT %s
            """, (device_code, pulse_param, c_start, c_end, _PULSE_CHUNK_LIMIT))
            chunk_rows = cur.fetchall()
            if len(chunk_rows) >= _PULSE_CHUNK_LIMIT:
                truncated.append(label)
            rows.extend(chunk_rows)
    return rows, truncated


def analyze_state_from_pulse(conn, device_code: str, device_name: str,
                              pulse_param: str, days: int = 7,
                              start_time: Optional[datetime] = None,
                              end_time: Optional[datetime] = None) -> Dict[str, Any]:
    """Step ③ 状态划分：基于脉搏参数+MySQL运行时段，分三类计算利用率。"""
    from datetime import timedelta
    from psycopg2.extras import RealDictCursor
    import statistics as st

    if start_time and end_time:
        end = end_time
        start = start_time
    else:
        end = datetime.now()
        start = end - timedelta(days=days)

    # 1. 拉脉搏参数原始数据（按班次分块，避免单次 LIMIT 丢掉窗口尾部）
    try:
        rows, truncated_chunks = _fetch_pulse_chunked(conn, device_code, pulse_param, start, end)
    except Exception as e:
        return {"error": f"查询失败: {e}", "step": 3}

    if not rows:
        return {"error": "无脉搏数据", "step": 3}

    vals = [r["v"] for r in rows]
    times = [r["point_time"] for r in rows]

    # 原始表有保留策略（device_alarm_info 只留 7 天），请求 30 天时窗口前段根本没有
    # 数据。若仍拿请求窗口当分母，被删掉的时间会被算成"离线"，利用率凭空腰斩 ——
    # 那是数据过期，不是设备停机。所以分母改用"实际覆盖到的范围"，并把截断情况
    # 回给前端提示，避免用户拿着失真的利用率做判断。
    effective_start = start
    window_truncated = False
    if times[0] > start + timedelta(hours=1):
        effective_start = times[0]
        window_truncated = True
    total_h = round((end - effective_start).total_seconds() / 3600, 1)

    # 2. 分类：与状态切片图同一口径——断档>N分钟判离线，其余按脉搏值>0=运行/值=0=非运行。
    #    以前卡片用「总时长−运行−非运行」残差反推离线，但值不变的长断档会被算进非运行，
    #    导致卡片离线≈0、时间轴离线却很大的矛盾（断档归了谁说不清）。
    #    统一从时间轴段累加，两处数值必然一致。
    timeline, timeline_totals = _build_state_timeline(times, vals, effective_start, end)

    running_h = timeline_totals["running_h"]
    idle_h = timeline_totals["idle_h"]
    offline_h = timeline_totals["offline_h"]
    running_segs = [
        {"start": sg["start"], "end": sg["end"], "hours": sg["hours"],
         "stage": round(float(vals[0]), 1)}
        for sg in timeline if sg["state"] == "running"
    ][:30]

    utilization = round(running_h / total_h * 100, 1) if total_h > 0 else 0
    # 设备运转率 = 运行 ÷ (总时长 - 离线时间)，即运行占"在线时长"的比例。
    # 离线(offline_h)是断档/关机时间，分母排除它才能体现设备真正上线时的运转水平。
    online_h = max(0.0, total_h - offline_h)
    operation_rate = round(running_h / online_h * 100, 1) if online_h > 0 else 0

    return {
        "step": 3, "days": days, "pulse_param": pulse_param,
        "total_hours": total_h,
        "requested_days": days,
        "window_truncated": window_truncated,
        "data_from": str(effective_start)[:19],
        "data_to": str(times[-1])[:19],
        # 哪些班次块的数据量撞到了取数上限（撞到才可能丢数据，正常情况为空）
        "chunk_truncated": truncated_chunks,
        "truncate_note": (
            f"原始数据仅保留到 {str(effective_start)[:16]}，请求的 {days} 天窗口只有"
            f" {round(total_h / 24, 1)} 天有数据；下列指标均按实际覆盖范围计算。"
            if window_truncated else None
        ),
        "chunk_truncate_note": (
            f"以下班次的采样点数达到取数上限（{_PULSE_CHUNK_LIMIT}），"
            f"这些班次的数据可能不完整：{'、'.join(truncated_chunks)}"
            if truncated_chunks else None
        ),
        "running_hours": running_h,
        "idle_hours": idle_h,
        "offline_hours": offline_h,
        "utilization": utilization,
        "operation_rate": operation_rate,
        "availability": operation_rate,
        "running_segments": running_segs[:30],
        "timeline": timeline,
        "timeline_totals": timeline_totals,
        "timeline_gap_minutes": _OFFLINE_GAP_MIN,
        "daily_breakdown": _daily_breakdown(times, vals, effective_start, end, pulse_param),
        "ai_insight": _state_ai_insight(device_name, pulse_param, total_h, running_h, idle_h, utilization, operation_rate, days),
        "summary": f"🏢资产利用率{utilization}% · 🔧设备运转率{operation_rate}%",
    }


# 采样断档超过这个分钟数就认为设备离线（没有上报＝没通电/没联网）
_OFFLINE_GAP_MIN = 10
# 时间线最多返回的段数，超了就把最短的段并进相邻段，避免响应过大
_TIMELINE_MAX_SEGS = 2000


def _build_state_timeline(times, vals, start, end):
    """把脉搏采样点切成 running/idle/offline 三态的连续时间段，供前端画状态切片图。

    - 相邻采样点间隔 > _OFFLINE_GAP_MIN 分钟：该区间判为 offline（数据断档）
    - 其余区间按区间起点的脉搏值判定：值 > 0 为 running，否则 idle
    - 窗口头尾没有数据覆盖的部分同样记为 offline

    注意：这里的 offline 是"按数据断档"算出来的，和外层
    offline_hours = total - running - idle 的残差算法口径不同，故单独返回
    timeline_totals，不覆盖原有字段。
    """
    from datetime import timedelta

    if not times:
        total_h = round((end - start).total_seconds() / 3600, 2)
        return [{"start": str(start)[:19], "end": str(end)[:19], "state": "offline", "hours": total_h}], \
            {"running_h": 0.0, "idle_h": 0.0, "offline_h": total_h, "segments": 1}

    gap = timedelta(minutes=_OFFLINE_GAP_MIN)
    segs = []

    def push(s_t, e_t, state):
        if e_t <= s_t:
            return
        if segs and segs[-1]["state"] == state and segs[-1]["end_dt"] == s_t:
            segs[-1]["end_dt"] = e_t          # 与前一段同态且相接 → 合并
        else:
            segs.append({"start_dt": s_t, "end_dt": e_t, "state": state})

    head_pushed = tail_pushed = False
    if times[0] - start > gap:
        push(start, times[0], "offline")
        head_pushed = True
    else:
        push(start, times[0], "running" if vals[0] > 0 else "idle")
        head_pushed = True

    for i in range(1, len(times)):
        prev_t, cur_t = times[i - 1], times[i]
        if cur_t - prev_t > gap:
            push(prev_t, cur_t, "offline")
        else:
            push(prev_t, cur_t, "running" if vals[i - 1] > 0 else "idle")

    if end - times[-1] > gap:
        push(times[-1], end, "offline")
        tail_pushed = True
    else:
        push(times[-1], end, "running" if vals[-1] > 0 else "idle")
        tail_pushed = True

    # 确保至少有一段（单数据点边界情况）
    if not segs:
        push(start, end, "running" if vals[0] > 0 else "idle")

    # 段数过多时，反复把最短的段并入相邻段（保持时间轴连续）
    while len(segs) > _TIMELINE_MAX_SEGS:
        k = min(range(len(segs)), key=lambda i: (segs[i]["end_dt"] - segs[i]["start_dt"]).total_seconds())
        if k == 0:
            segs[1]["start_dt"] = segs[0]["start_dt"]
        elif k == len(segs) - 1:
            segs[-2]["end_dt"] = segs[-1]["end_dt"]
        else:
            prev_len = (segs[k - 1]["end_dt"] - segs[k - 1]["start_dt"]).total_seconds()
            next_len = (segs[k + 1]["end_dt"] - segs[k + 1]["start_dt"]).total_seconds()
            if prev_len >= next_len:
                segs[k - 1]["end_dt"] = segs[k]["end_dt"]
            else:
                segs[k + 1]["start_dt"] = segs[k]["start_dt"]
        segs.pop(k)
        # 合并后可能出现相邻同态段，顺手粘一次
        merged = []
        for sg in segs:
            if merged and merged[-1]["state"] == sg["state"] and merged[-1]["end_dt"] == sg["start_dt"]:
                merged[-1]["end_dt"] = sg["end_dt"]
            else:
                merged.append(sg)
        segs = merged

    totals = {"running": 0.0, "idle": 0.0, "offline": 0.0}
    out = []
    for sg in segs:
        dur = (sg["end_dt"] - sg["start_dt"]).total_seconds()
        totals[sg["state"]] += dur
        out.append({
            "start": str(sg["start_dt"])[:19],
            "end": str(sg["end_dt"])[:19],
            "state": sg["state"],
            "hours": round(dur / 3600, 3),
        })

    return out, {
        "running_h": round(totals["running"] / 3600, 2),
        "idle_h": round(totals["idle"] / 3600, 2),
        "offline_h": round(totals["offline"] / 3600, 2),
        "segments": len(out),
    }


def analyze_efficiency(conn, device_code: str, device_name: str,
                       pulse_param: str, days: int = 7) -> Dict[str, Any]:
    """Step ④ 效率分析：识别"房子"波形，算产量/节拍/OEE/运转率/产品类型/质量。"""
    from datetime import timedelta
    from psycopg2.extras import RealDictCursor
    import statistics as st

    end = datetime.now()
    start = end - timedelta(days=days)
    total_h = round((end - start).total_seconds() / 3600, 1)

    # 1. 拉脉搏原始数据
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '30s'")
            cur.execute("""
                SELECT a.point_value::double precision AS v, a.point_time
                FROM device_alarm_info a
                WHERE a.device_id = %s AND a.point_id = %s
                  AND a.point_time >= %s AND a.point_time <= %s
                  AND a.point_value IS NOT NULL
                ORDER BY a.point_time LIMIT 50000
            """, (device_code, pulse_param, start, end))
            rows = cur.fetchall()
    except Exception as e:
        return {"error": f"查询脉搏数据失败: {e}"}

    if not rows:
        return {"error": "该时间段内无脉搏数据"}

    vals = [r["v"] for r in rows]
    times = [r["point_time"] for r in rows]

    # 2. 识别"房子"（完整生产周期：0→>0→plateau→0→下一个）
    houses = []
    in_house = False
    house_start = None
    house_max_val = 0
    house_min_time = None
    plateau_start = None
    peak_threshold = 0

    # 先估算峰值阈值（中位数以上才算 plateau）
    non_zero = [v for v in vals if v > 0]
    if non_zero:
        peak_threshold = st.median(non_zero) * 0.6  # 峰值60%以上算稳定生产

    for i in range(len(vals)):
        v = vals[i]
        t = times[i]
        if not in_house and v > 0:
            # 进入房子：脉搏从0升起
            in_house = True
            house_start = t
            house_min_time = t
            house_max_val = v
            plateau_start = None
        elif in_house:
            if v > house_max_val:
                house_max_val = v
            # 判断是否进入plateau（脉搏稳定在峰值附近）
            if plateau_start is None and peak_threshold > 0 and v >= peak_threshold:
                plateau_start = t
            if v == 0 or i == len(vals) - 1:
                # 房子结束
                house_end = t
                dur_total = round((house_end - house_start).total_seconds() / 60, 1)  # 分钟
                plateau_dur = 0
                if plateau_start and house_end > plateau_start:
                    plateau_dur = round((house_end - plateau_start).total_seconds() / 60, 1)
                idle_dur = max(0, round(dur_total - plateau_dur, 1))  # 空跑（升+降）

                houses.append({
                    "index": len(houses) + 1,
                    "start": str(house_start)[:19],
                    "end": str(house_end)[:19],
                    "duration_min": dur_total,
                    "plateau_min": plateau_dur,
                    "idle_min": idle_dur,       # 空跑
                    "peak_value": round(house_max_val, 1),
                })
                in_house = False
                house_max_val = 0

    # 3. 统计
    total_houses = len(houses)
    total_plateau = sum(h["plateau_min"] for h in houses)
    total_idle = sum(h["idle_min"] for h in houses)
    house_total = total_plateau + total_idle  # 房子总时间（分钟）

    # 草坪时间 = 脉搏为0但有数据的时段（从state analysis复用）
    lawn_min = 0
    for i in range(1, len(vals)):
        if vals[i] == vals[i-1] == 0:
            lawn_min += (times[i] - times[i-1]).total_seconds() / 60

    lawn_min = round(lawn_min, 1)
    house_total_m = round(house_total, 1)

    # 运转率 = 房子 / (房子 + 草坪)
    run_rate = round(house_total_m / (house_total_m + lawn_min) * 100, 1) if (house_total_m + lawn_min) > 0 else 0

    # 4. 尝试识别产品类型（按房子时长聚类）
    product_types = _identify_product_types(houses)

    # 5. 尝试读取质量相关参数（温度、真空度、重量）做质量判定
    quality_results = _analyze_house_quality(conn, device_code, houses, start, end)

    # 6. OEE 估算
    # OEE = 时间利用率 × 性能效率 × 合格率
    time_util = run_rate  # 时间利用率 ≈ 运转率
    # 性能效率：实际节拍 vs 理论节拍（取最短房子时长作为理论节拍）
    if houses:
        min_cycle = min(h["duration_min"] for h in houses)
        avg_cycle = st.mean([h["duration_min"] for h in houses])
        perf_rate = round(min_cycle / avg_cycle * 100, 1) if avg_cycle > 0 else 100
    else:
        perf_rate = 0
    # 合格率
    if quality_results.get("total", 0) > 0:
        quality_rate = round(quality_results.get("passed", 0) / quality_results["total"] * 100, 1)
    else:
        quality_rate = 100
    oee = round(time_util * perf_rate / 100 * quality_rate / 100, 1)

    # 7. AI 洞察
    insight_data = {
        "device_name": device_name, "days": days, "pulse_param": pulse_param,
        "total_houses": total_houses, "run_rate": run_rate, "oee": oee,
        "time_util": time_util, "perf_rate": perf_rate, "quality_rate": quality_rate,
        "product_types": product_types,
    }
    ai_text = _efficiency_ai_insight(insight_data)

    return {
        "step": 4, "days": days, "pulse_param": pulse_param,
        "total_houses": total_houses,
        "house_total_min": house_total_m,
        "lawn_min": lawn_min,
        "run_rate": run_rate,         # 运转率 房子/(房子+草坪)
        "oee": oee,
        "time_utilization": time_util,
        "performance_rate": perf_rate,
        "quality_rate": quality_rate,
        "houses": houses[:50],         # 最近50栋房子详情
        "product_types": product_types,
        "quality": quality_results,
        "ai_insight": ai_text,
        "summary": f"🏠{total_houses}栋房子 · ⚡运转率{run_rate}% · 📊OEE {oee}%",
    }


def _identify_product_types(houses: list) -> list:
    """按房子时长聚类识别产品类型。"""
    if len(houses) < 2:
        return [{"name": "默认型号", "count": len(houses), "avg_cycle_min": round(houses[0]["duration_min"], 1) if houses else 0}]

    from collections import Counter
    # 简单按10分钟区间分组
    clusters = Counter()
    for h in houses:
        bucket = round(h["duration_min"] / 10) * 10
        clusters[bucket] += 1

    # 取TOP3时长区间作为产品类型
    types = []
    for bucket, count in clusters.most_common(3):
        bucket_houses = [h for h in houses if round(h["duration_min"] / 10) * 10 == bucket]
        avg_cycle = round(sum(h["duration_min"] for h in bucket_houses) / len(bucket_houses), 1)
        avg_plateau = round(sum(h["plateau_min"] for h in bucket_houses) / len(bucket_houses), 1)
        avg_idle = round(sum(h["idle_min"] for h in bucket_houses) / len(bucket_houses), 1)
        # 给型号起名
        name = f"型号{chr(65 + len(types))}"  # A, B, C
        types.append({
            "name": name,
            "count": count,
            "avg_cycle_min": avg_cycle,
            "avg_plateau_min": avg_plateau,
            "avg_idle_min": avg_idle,
            "cycle_range": f"{round(min(h['duration_min'] for h in bucket_houses), 1)}~{round(max(h['duration_min'] for h in bucket_houses), 1)}min",
        })
    return types


def _analyze_house_quality(conn, device_code: str, houses: list, start, end) -> dict:
    """用温度、真空度、重量参数判定每栋房子的质量。"""
    from psycopg2.extras import RealDictCursor

    if not houses:
        return {"total": 0, "passed": 0, "failed": 0, "details": []}

    # 尝试读取温度/真空度/重量数据
    quality_params = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT p.p_name, p.p_display_name, p.p_unit
                FROM device_point p
                WHERE p.device_id = %s
                  AND (p.p_name ILIKE '%tep%' OR p.p_name ILIKE '%vacuum%'
                       OR p.p_name ILIKE '%weight%' OR p.p_name ILIKE '%temp%')
                LIMIT 5
            """, (device_code,))
            quality_params = cur.fetchall()
    except Exception as e:
        print(f"[房子质量] 质量参数查询失败 device={device_code}: {e}")

    details = []
    for h in houses:
        h_start = h["start"]
        h_end = h["end"]
        house_result = {"house": h["index"], "passed": True, "params": {}}
        for p in quality_params:
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT AVG(a.point_value::double precision) AS avg_val,
                               STDDEV(a.point_value::double precision) AS std_val
                        FROM device_alarm_info a
                        WHERE a.device_id = %s AND a.point_id = %s
                          AND a.point_time >= %s AND a.point_time <= %s
                    """, (device_code, p["p_name"], h_start, h_end))
                    row = cur.fetchone()
                    if row and row["avg_val"] is not None:
                        house_result["params"][p["p_display_name"] or p["p_name"]] = {
                            "avg": round(float(row["avg_val"]), 1),
                            "std": round(float(row["std_val"] or 0), 1),
                            "unit": p["p_unit"] or "",
                        }
            except Exception as e:
                print(f"[房子质量] 参数 {p.get('p_name')} 统计失败: {e}")
        details.append(house_result)

    passed = sum(1 for d in details if d["passed"])
    return {"total": len(houses), "passed": passed, "failed": len(houses) - passed, "quality_params": quality_params, "details": details}


def _efficiency_ai_insight(data: dict) -> str:
    """用LLM生成效率分析洞察。"""
    try:
        import asyncio
        async def _call():
            llm = get_llm()
            pt = data.get("product_types", [])
            pt_text = "\n".join([f"  · {t['name']}: {t['count']}栋, 平均节拍{t['avg_cycle_min']}min"
                                  for t in pt]) if pt else "  未识别"
            prompt = f"""你是一位工业设备效率分析师。设备{data['device_name']}最近{data['days']}天效率分析：

=== 数据来源 ===
脉搏参数「{data['pulse_param']}」的时序波形 → 按0→升→稳定→降→0识别"房子"（完整生产周期）
- 房子 = 一次完整生产（含升程+稳定+降程）
- 空跑 = 升降过程中不产出的部分
- 草坪 = 脉搏值为0的在线空闲时段

=== 分析结果 ===
- 总产量：{data['total_houses']} 栋房子
- 运转率：{data['run_rate']}%（房子总时间 ÷ (房子+草坪)总时间）
- OEE：{data['oee']}%（时间利用率{data['time_util']}% × 性能效率{data['perf_rate']}% × 合格率{data['quality_rate']}%）

产品类型识别：
{pt_text}

请给出详细诊断（150-300字）：
1. 运转率和OEE水平评价
2. 空跑（升降过程）占比是否合理，优化空间
3. 不同产品型号的节拍差异分析
4. 可量化的改进建议"""
            resp = await llm.chat.completions.create(
                model=CONFIG["model"], messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=500,
            )
            return resp.choices[0].message.content.strip()
        return asyncio.run(_call())
    except Exception:
        return None


def _daily_breakdown(times, vals, start, end, pulse_param):
    """按天切分统计数据（与状态切片图同一口径：断档>N分钟判离线）。"""
    from collections import defaultdict
    from datetime import datetime, timedelta

    timeline, _ = _build_state_timeline(times, vals, start, end)
    days = defaultdict(lambda: {"running": 0.0, "idle": 0.0, "offline": 0.0, "segments": 0})

    for sg in timeline:
        seg_start = datetime.strptime(sg["start"], "%Y-%m-%d %H:%M:%S")
        seg_end = datetime.strptime(sg["end"], "%Y-%m-%d %H:%M:%S")
        day = seg_start.date()
        day_end = datetime(day.year, day.month, day.day) + timedelta(days=1)
        # 跨天段：按落在各天的时长拆分，避免整段记到开始那天
        while seg_start < seg_end:
            boundary = min(seg_end, day_end)
            dur_h = (boundary - seg_start).total_seconds() / 3600
            key = seg_start.strftime("%Y-%m-%d")
            days[key][sg["state"]] += round(dur_h, 6)
            days[key]["segments"] += 1
            seg_start = boundary
            day_end = boundary.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    result = []
    for day in sorted(days.keys()):
        d = days[day]
        total = d["running"] + d["idle"] + d["offline"]
        online = max(0.0, total - d["offline"])
        result.append({
            "date": day,
            "running_h": round(d["running"], 1),
            "idle_h": round(d["idle"], 1),
            "offline_h": round(d["offline"], 1),
            "utilization": round(d["running"] / total * 100, 1) if total > 0 else 0,
            "operation_rate": round(d["running"] / online * 100, 1) if online > 0 else 0,
            "segments": d["segments"],
        })
    return result


def _state_ai_insight(device_name, pulse_param, total_h, running_h, idle_h, utilization, operation_rate, days):
    """用LLM生成状态分析洞察（同步调用）。"""
    try:
        import asyncio
        async def _call():
            llm = get_llm()
            prompt = f"""你是一位工业设备数据分析师。以下是设备「{device_name}」在最近{days}天的状态分析结果：

=== 数据来源与方法 ===
- 数据源：TimescaleDB 时序库 device_alarm_info 表，查询脉搏参数「{pulse_param}」的原始时序值
- 分析方法：逐值变化检测——脉搏参数值发生变化时切段
  · 脉搏值 > 0 的时段 → 判定为「运行」（设备生产作业中）
  · 脉搏值 = 0 的时段 → 判定为「空闲」（设备上电但未生产）
  · 无数据的时段   → 判定为「离线」（设备断网或关机）

=== 分析结果 ===
- 分析窗口：最近{days}天，总计 {total_h} 小时
- 运行时长：{running_h} 小时（资产利用率 {utilization}%）
- 空闲时长：{idle_h} 小时
- 离线时长：{round(total_h - running_h - idle_h, 2)} 小时
- 设备运转率：{operation_rate}%（运行 / 在线时长，在线时长=总时长-离线）
- 离线时长：{round(total_h - running_h - idle_h, 2)} 小时

=== 计算公式 ===
资产利用率 = 运行时长 ÷ 总时长 × 100% = {running_h} ÷ {total_h} × 100% = {utilization}%
设备运转率 = 运行时长 ÷ (总时长 - 离线时长) × 100% = {running_h} ÷ {round(total_h - round(total_h - running_h - idle_h, 2), 2)} × 100% = {operation_rate}%

请从以下角度给出详细诊断（150-300字）：
1. 当前设备运行效率评价（高/中/低，为什么）
2. 空闲和离线时间的根因推测（是排产不合理？等待物料？设备故障？）
3. 可量化的改进建议（如：将空闲率降低X%可使利用率提升至Y%）
4. 是否需要进一步分析特定时段的异常（如深夜空闲、工作日离线等）"""
            resp = await llm.chat.completions.create(
                model=CONFIG["model"], messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=500,
            )
            return resp.choices[0].message.content.strip()
        return asyncio.run(_call())
    except Exception:
        return None
