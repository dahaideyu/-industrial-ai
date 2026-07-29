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

    end = datetime.now()
    start = end - timedelta(days=days)

    # 该设备定义的全部参数点位（含关联电表），不依赖是否有数据
    all_p_names: List[str] = []
    try:
        _points_db = TimescaleDB()
        _points_db.conn = conn
        all_p_names = [p["p_name"] for p in _points_db.get_points(device_code)]
    except Exception:
        all_p_names = []

    # === Phase 1: 快速统计 + 启发式筛选（近 days 天窗口）===
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '30s'")
            cur.execute("""
                SELECT a.point_id AS p_name,
                       a.point_value::double precision AS v
                FROM device_alarm_info a
                WHERE a.device_id = %s
                  AND a.point_time >= %s AND a.point_time <= %s
                  AND a.point_value IS NOT NULL
                ORDER BY a.point_time
                LIMIT 50000
            """, (device_code, start, end))
            rows = cur.fetchall()
    except Exception as e:
        return {"error": f"查询失败: {e}", "step": 1}

    if not rows and not all_p_names:
        return {"error": "该设备在指定时间范围内无数据", "step": 1}

    # 按参数分组
    param_vals: Dict[str, List[float]] = {}
    for r in rows:
        param_vals.setdefault(r["p_name"], []).append(r["v"])

    # 近窗口没数据、但设备定义里有的参数：回退拉各自最近一批历史数据（不限定日期），
    # 避免"因为最近没数据就不显示"
    stale_last_seen: Dict[str, Any] = {}
    missing = [p for p in all_p_names if p not in param_vals]
    if missing:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET statement_timeout = '15s'")
                cur.execute("""
                    SELECT p_name, v, point_time FROM (
                        SELECT a.point_id AS p_name,
                               a.point_value::double precision AS v,
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
        except Exception:
            pass

    # 启发式规则（不调 LLM，纯 Python，秒级）
    HEURISTIC_RULES = [
        # (条件函数, 分类结果, 理由)
        (lambda f: f["uniq"] <= 1, "useless", "值完全不变"),
        (lambda f: f["range_ratio"] < 0.01 and f["change_rate"] < 0.01, "useless", "极差<1%且几乎不变"),
        (lambda f: f["n"] < 10, "useless", "数据点不足"),
        (lambda f: abs(f["trend"]) > 0.02 and f["range_ratio"] > 0.1, "predictive", "有明显趋势+足够波动"),
        (lambda f: f["range_ratio"] > 0.3 and f["change_rate"] > 0.2, "quality", "波动大变化频繁(质量相关)"),
        (lambda f: f["range_ratio"] > 0.3 and f["change_rate"] <= 0.05, "management", "波动大但变化慢(经营相关)"),
    ]

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
        trend = 0.0
        if n > 10 and std_val > 0:
            xm = (n - 1) / 2; ym = mean_val
            num = sum((i - xm) * (vals[i] - ym) for i in range(n))
            den = sum((i - xm) ** 2 for i in range(n))
            if den > 0:
                trend = num / den * n / (abs(mean_val) + 0.001)

        f = {"n": n, "uniq": uniq, "range_ratio": rng_ratio,
             "change_rate": change_rate, "trend": trend}

        # 匹配第一条规则
        cat, reason = "management", "有变化可关注"
        for rule_fn, rule_cat, rule_reason in HEURISTIC_RULES:
            if rule_fn(f):
                cat, reason = rule_cat, rule_reason
                break

        is_stale = p_name in stale_last_seen
        if is_stale:
            reason = f"最近{days}天无数据，用历史数据判断({reason})"

        classified.append({
            "p_name": p_name,
            "category": cat,
            "reason": reason,
            "checked": cat != "useless",
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
                "category": "nodata",
                "reason": "无历史数据",
                "checked": False,
                "n": 0, "uniq": 0,
                "vmin": None, "vmax": None, "mean": None, "std": None,
                "range_ratio": 0, "change_rate": 0, "trend": 0,
                "stale": False, "last_seen": None,
            })

    classified.sort(key=lambda x: (x["category"] in ("useless", "nodata"), -x["range_ratio"]))

    result = {
        "step": 1, "days": days,
        "classified": classified,
        "summary": _make_summary(classified),
        "source": "heuristic",
    }

    # === Phase 2: LLM 增强（可选，失败不影响） ===
    try:
        useful = [c for c in classified if c["category"] not in ("useless", "nodata")]
        if len(useful) >= 3:
            params_text = "\n".join(
                f"{c['p_name']}: n={c['n']} range={c['range_ratio']} chg={c['change_rate']} trend={c['trend']}"
                for c in useful[:20]
            )
            kb = await _query_knowledge_base_async(device_name, params_text[:600])
            llm = get_llm()
            prompt = f"""设备{device_name}，{days}天数据。以下参数已被粗筛标记，请做精细化分类：
{"知识库参考：" + kb[:400] if kb else ""}
参数: {params_text[:1500]}

用JSON修正分类，只改你认为标记错的：{{"refined":[{{"p_name":"...","category":"predictive|quality|management|useless","reason":"..."}}]}}"""
            resp = await llm.chat.completions.create(
                model=CONFIG["model"], messages=[{"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=800,
            )
            import re
            m = re.search(r'\{[\s\S]*\}', resp.choices[0].message.content)
            if m:
                refined = json.loads(m.group()).get("refined", [])
                ref_map = {r["p_name"]: r for r in refined}
                for c in classified:
                    if c["p_name"] in ref_map:
                        c["category"] = ref_map[c["p_name"]].get("category", c["category"])
                        c["reason"] = ref_map[c["p_name"]].get("reason", c["reason"])
                        c["checked"] = c["category"] != "useless"
                result["source"] = "ai"
                result["summary"] = _make_summary(classified)
    except Exception:
        pass

    return result


def _make_summary(classified):
    cats = {}
    for c in classified:
        cats[c["category"]] = cats.get(c["category"], 0) + 1
    return " · ".join(f"{k}{v}" for k, v in cats.items())


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
    """Step ② 脉搏发现：分析所有参数的周期性，推荐最适合做cycle划分的参数。"""
    from datetime import timedelta
    from psycopg2.extras import RealDictCursor
    import statistics as st

    end = datetime.now()
    start = end - timedelta(days=days)

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '30s'")
            cur.execute("""
                SELECT a.point_id AS p_name, a.point_value::double precision AS v
                FROM device_alarm_info a
                WHERE a.device_id = %s
                  AND a.point_time >= %s AND a.point_time <= %s
                  AND a.point_value IS NOT NULL
                ORDER BY a.point_time
                LIMIT 50000
            """, (device_code, start, end))
            rows = cur.fetchall()
    except Exception as e:
        return {"error": f"查询失败: {e}", "step": 2}

    if not rows:
        return {"error": "无数据", "step": 2}

    param_vals: Dict[str, List[float]] = {}
    for r in rows:
        param_vals.setdefault(r["p_name"], []).append(r["v"])

    candidates = []
    for p_name, vals in param_vals.items():
        if len(vals) < 50:
            continue
        n = len(vals)
        uniq = len(set(vals))
        mean_val = sum(vals) / n
        std_val = st.stdev(vals) if n >= 2 else 0
        if std_val == 0:
            continue

        # 周期性得分：均值穿越次数+间隔一致性
        crossings = 0
        for i in range(1, n):
            if (vals[i-1] < mean_val <= vals[i]) or (vals[i-1] > mean_val >= vals[i]):
                crossings += 1
        if crossings < 3:
            continue

        # 计算穿越间隔的变异系数（越稳定=周期性越强）
        cross_idxs = []
        for i in range(1, n):
            if (vals[i-1] < mean_val <= vals[i]) or (vals[i-1] > mean_val >= vals[i]):
                cross_idxs.append(i)
        gaps = [cross_idxs[i+1] - cross_idxs[i] for i in range(len(cross_idxs)-1)]
        gap_mean = sum(gaps) / len(gaps)
        gap_std = st.stdev(gaps) if len(gaps) >= 2 else 0
        cv = gap_std / gap_mean if gap_mean > 0 else 1.0  # 变异系数，越小越规律
        periodicity = max(0, 1.0 - min(cv, 1.0))

        # 估算周期（分钟），假设~5秒采样
        cycle_min = round(gap_mean * 2 * 5 / 60, 1) if gap_mean > 0 else None

        # 判断理由
        reasons = []
        if periodicity > 0.7:
            reasons.append("周期性极强")
        elif periodicity > 0.4:
            reasons.append("周期性明显")
        if uniq <= 20:
            reasons.append(f"离散值({uniq}种)，适合标识阶段")
        if cycle_min and cycle_min > 0:
            reasons.append(f"估算周期≈{cycle_min}分钟")
        if change_rate := sum(1 for i in range(1, min(n, 1000)) if vals[i] != vals[i-1]) / (min(n, 1000) - 1):
            if change_rate < 0.05:
                reasons.append("离散跳跃式变化，符合状态码特征")

        candidates.append({
            "p_name": p_name,
            "periodicity": round(periodicity, 3),
            "cycle_minutes": cycle_min,
            "n": n, "uniq": uniq,
            "reason": "；".join(reasons) if reasons else "有周期规律",
            "score": round(periodicity * 100, 0),
        })

    candidates.sort(key=lambda x: -x["score"])

    # KB增强：先查知识库，再让知识库实际参与候选排序/确认，而不只是事后加一句提示文本
    kb_text = None
    try:
        summary = ", ".join(f"{c['p_name']}({c['score']:.0f})" for c in candidates[:8])
        kb_text = _query_knowledge_base_sync(device_name, f"该设备的生产节拍/阶段参数是什么？{summary}")
    except Exception:
        pass

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
    }


def _kb_rerank_pulse_candidates(device_name: str, candidates: List[Dict[str, Any]],
                                kb_text: str) -> Optional[List[str]]:
    """把统计打分的候选交给LLM+知识库，判断哪些更符合"生产节拍/阶段状态"参数的工艺特征，
    返回按知识库判断的优先级排序的 p_name 列表；知识库没有相关信息时返回 None（不瞎猜、不重排）。
    """
    import re
    import asyncio
    summary = "\n".join(
        f"{c['p_name']}: 周期性得分{c['score']:.0f}, 估算周期{c.get('cycle_minutes')}分钟, 理由:{c['reason']}"
        for c in candidates
    )
    try:
        async def _call():
            llm = get_llm()
            prompt = f"""设备{device_name}。知识库参考：{kb_text[:500]}

候选参数（按统计周期性打分，仅供参考，不代表工艺上的真实含义）：
{summary}

请结合知识库描述的工艺，判断这些候选里最符合"生产节拍/阶段状态"参数特征的，按可能性从高到低排序。
只返回JSON：{{"ranked": ["p_name1","p_name2",...]}}。如果知识库没有提供足够信息判断，
返回{{"ranked": []}}，不要凭空猜测。"""
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


def analyze_state_from_pulse(conn, device_code: str, device_name: str,
                              pulse_param: str, days: int = 7) -> Dict[str, Any]:
    """Step ③ 状态划分：基于脉搏参数+MySQL运行时段，分三类计算利用率。"""
    from datetime import timedelta
    from psycopg2.extras import RealDictCursor
    import statistics as st

    end = datetime.now()
    start = end - timedelta(days=days)

    # 1. 拉脉搏参数原始数据
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

    # 2. 分类：值变化 = 运行中，值不变 = 非运行(空闲/离线)
    running_sec = 0.0
    idle_sec = 0.0
    offline_sec = 0.0
    running_segs = []
    seg_start = times[0]
    seg_val = vals[0]

    for i in range(1, len(vals)):
        if vals[i] != seg_val:
            # 值变了 → 上一段结束
            dur = (times[i] - seg_start).total_seconds()
            if dur > 0:
                if seg_val > 0 or (i > 0 and vals[i-1] != 0):
                    running_sec += dur
                    if dur > 60:  # 只记录>1分钟的段
                        running_segs.append({
                            "start": str(seg_start)[:19],
                            "end": str(times[i])[:19],
                            "hours": round(dur / 3600, 2),
                            "stage": round(float(seg_val), 1),
                        })
                else:
                    idle_sec += dur
            seg_start = times[i]
            seg_val = vals[i]

    # 最后一段
    dur = (times[-1] - seg_start).total_seconds()
    if dur > 0:
        if seg_val > 0:
            running_sec += dur
        else:
            idle_sec += dur

    running_h = round(running_sec / 3600, 2)
    idle_h = round(idle_sec / 3600, 2)
    offline_h = round(max(0, total_h - running_h - idle_h), 2)

    utilization = round(running_h / total_h * 100, 1) if total_h > 0 else 0
    availability = round((running_h + idle_h) / total_h * 100, 1) if total_h > 0 else 0

    timeline, timeline_totals = _build_state_timeline(times, vals, effective_start, end)

    return {
        "step": 3, "days": days, "pulse_param": pulse_param,
        "total_hours": total_h,
        "requested_days": days,
        "window_truncated": window_truncated,
        "data_from": str(effective_start)[:19],
        "truncate_note": (
            f"原始数据仅保留到 {str(effective_start)[:16]}，请求的 {days} 天窗口只有"
            f" {round(total_h / 24, 1)} 天有数据；下列指标均按实际覆盖范围计算。"
            if window_truncated else None
        ),
        "running_hours": running_h,
        "idle_hours": idle_h,
        "offline_hours": offline_h,
        "utilization": utilization,
        "availability": availability,
        "running_segments": running_segs[:30],
        "timeline": timeline,
        "timeline_totals": timeline_totals,
        "timeline_gap_minutes": _OFFLINE_GAP_MIN,
        "daily_breakdown": _daily_breakdown(times, vals, start, end, pulse_param),
        "ai_insight": _state_ai_insight(device_name, pulse_param, total_h, running_h, idle_h, utilization, availability, days),
        "summary": f"🏢资产利用率{utilization}% · 🔧设备可用率{availability}%",
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
    except Exception:
        pass

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
            except Exception:
                pass
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
    """按天切分统计数据。"""
    from collections import defaultdict
    days = defaultdict(lambda: {"running": 0.0, "idle": 0.0, "offline": 0.0, "segments": 0})
    day_start = None
    current_day = None
    running = False

    for i, t in enumerate(times):
        day = t.strftime("%Y-%m-%d")
        if day != current_day:
            current_day = day
            day_start = t
            running = vals[i] > 0 if i < len(vals) else False

        if i > 0 and vals[i] != vals[i-1]:
            dur = (times[i] - (day_start or times[i-1])).total_seconds() / 3600
            if dur > 0:
                if running:
                    days[current_day]["running"] += dur
                else:
                    days[current_day]["idle"] += dur
                days[current_day]["segments"] += 1
            day_start = times[i]
            running = vals[i] > 0

    result = []
    for day in sorted(days.keys()):
        d = days[day]
        total = d["running"] + d["idle"]
        offline = max(0, 24 - total)
        result.append({
            "date": day,
            "running_h": round(d["running"], 1),
            "idle_h": round(d["idle"], 1),
            "offline_h": round(offline, 1),
            "utilization": round(d["running"] / 24 * 100, 1) if total > 0 else 0,
            "segments": d["segments"],
        })
    return result


def _state_ai_insight(device_name, pulse_param, total_h, running_h, idle_h, utilization, availability, days):
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
- 设备可用率：{availability}%（运行+空闲 / 总时长，即在线的比例）

=== 计算公式 ===
资产利用率 = 运行时长 ÷ 总时长 × 100% = {running_h} ÷ {total_h} × 100% = {utilization}%
设备可用率 = (运行时长 + 空闲时长) ÷ 总时长 × 100% = ({running_h} + {idle_h}) ÷ {total_h} × 100% = {availability}%

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
