# cython: annotation_typing=False, infer_types=False, language_level=3
"""班次（Shift）——设备分析的基本时间单位。

合膏机默认两班倒：
- 白班 day  ：当日 06:00 → 当日 18:00
- 晚班 night：当日 18:00 → 次日 06:00（跨天）

**班次归属日期**：晚班跨天，统一归属"开始的那一天"。
所以 8/4 凌晨 03:00 属于 `8/3 晚班`，不是 8/4。这是现场交接班的习惯口径，
也保证「某一天的白班+晚班」正好是连续 24 小时、不重不漏。

为什么把班次做成基本单位（而不是任意起止时间）：
1. OEE 的可用率需要一个"计划生产时间"当分母。用任意时间窗算出来的是 TEEP，
   不是 OEE；用班次时长当分母，OEE 才名副其实。
2. 班次一旦结束，其数据不再变化 → 分析结果可以永久缓存；进行中的班次
   必须标记 partial，不能当成最终结果存下来。
3. 现场的考核单位就是班次，按班次出的数字才能直接落到班组。

班制目前是常量默认值。不同设备/车间若有不同班制（如三班倒），
把 ShiftConfig 存进按设备的配置表再传进来即可，本模块所有函数都接受
可选的 cfg 参数，不需要改调用方逻辑。
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

SHIFT_DAY = "day"
SHIFT_NIGHT = "night"
SHIFT_FULL = "full"     # 天粒度：06:00 → 次日06:00，覆盖白班+晚班整整 24 小时

SHIFT_LABELS = {SHIFT_DAY: "白班", SHIFT_NIGHT: "晚班", SHIFT_FULL: "全天"}


@dataclass(frozen=True)
class ShiftConfig:
    """班制定义。默认两班倒，白班 06:00 起，每班 12 小时。"""
    day_start_hour: int = 6
    shift_hours: int = 12

    @property
    def night_start_hour(self) -> int:
        return self.day_start_hour + self.shift_hours


DEFAULT_SHIFT_CONFIG = ShiftConfig()


@dataclass(frozen=True)
class ShiftWindow:
    """一个具体的班次实例（某天的白班/晚班）。"""
    shift_date: date        # 归属日期（晚班取开始那天）
    shift_type: str         # day / night
    start: datetime
    end: datetime

    @property
    def key(self) -> str:
        """稳定的缓存/持久化键，如 20260803-night。"""
        return f"{self.shift_date:%Y%m%d}-{self.shift_type}"

    @property
    def label(self) -> str:
        """给人看的名字，如 08-03 晚班。"""
        return f"{self.shift_date:%m-%d} {SHIFT_LABELS.get(self.shift_type, self.shift_type)}"

    @property
    def full_label(self) -> str:
        return f"{self.shift_date:%Y-%m-%d} {SHIFT_LABELS.get(self.shift_type, self.shift_type)}"

    @property
    def hours(self) -> float:
        """班次时长（小时）——OEE 的计划生产时间分母。"""
        return (self.end - self.start).total_seconds() / 3600

    def is_closed(self, now: Optional[datetime] = None) -> bool:
        """班次是否已经结束。已结束的班次数据不再变化，分析结果可永久缓存。"""
        return self.end <= (now or datetime.now())

    def clip(self, start: datetime, end: datetime) -> Optional["ShiftWindow"]:
        """把班次裁剪到 [start, end] 内。完全不相交返回 None。

        用于用户选的时间范围只覆盖某个班次一部分时——此时该班次的指标
        只能按裁剪后的实际范围算，调用方应据此标注"不完整"。
        """
        s, e = max(self.start, start), min(self.end, end)
        if e <= s:
            return None
        return ShiftWindow(self.shift_date, self.shift_type, s, e)

    @property
    def is_partial(self) -> bool:
        """是否被裁剪过（时长短于该类型的整窗时长）。

        full 粒度(SHIFT_FULL)是白班+晚班两个整班拼起来的 24 小时，期望时长要
        乘 2，否则一个被截断到 18 小时的"天"窗口会被误判成"没有被裁剪"。
        """
        expected_hours = DEFAULT_SHIFT_CONFIG.shift_hours * (2 if self.shift_type == SHIFT_FULL else 1)
        return (self.end - self.start) < timedelta(hours=expected_hours)

    def to_dict(self, now: Optional[datetime] = None) -> dict:
        return {
            "key": self.key,
            "shift_date": self.shift_date.strftime("%Y-%m-%d"),
            "shift_type": self.shift_type,
            "shift_name": SHIFT_LABELS.get(self.shift_type, self.shift_type),
            "label": self.label,
            "full_label": self.full_label,
            "start": self.start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": self.end.strftime("%Y-%m-%d %H:%M:%S"),
            "hours": round(self.hours, 2),
            "closed": self.is_closed(now),
            "partial": self.is_partial,
        }


def shift_bounds(shift_date: date, shift_type: str,
                 cfg: ShiftConfig = DEFAULT_SHIFT_CONFIG) -> ShiftWindow:
    """构造某天某班次的时间窗。晚班的 end 落在次日。"""
    if shift_type == SHIFT_DAY:
        start = datetime.combine(shift_date, datetime.min.time()).replace(hour=cfg.day_start_hour)
        end = start + timedelta(hours=cfg.shift_hours)
    elif shift_type == SHIFT_NIGHT:
        start = datetime.combine(shift_date, datetime.min.time()).replace(hour=cfg.night_start_hour % 24)
        if cfg.night_start_hour >= 24:
            start += timedelta(days=1)
        end = start + timedelta(hours=cfg.shift_hours)
    else:
        raise ValueError(f"未知班次类型: {shift_type}")
    return ShiftWindow(shift_date, shift_type, start, end)


def full_day_bounds(day: date, cfg: ShiftConfig = DEFAULT_SHIFT_CONFIG) -> ShiftWindow:
    """构造某天的"天"窗口：06:00(白班起点) → 次日 06:00，正好是白班+晚班整整 24 小时。"""
    start = datetime.combine(day, datetime.min.time()).replace(hour=cfg.day_start_hour)
    end = start + timedelta(hours=cfg.shift_hours * 2)
    return ShiftWindow(day, SHIFT_FULL, start, end)


def shift_of(dt: datetime, cfg: ShiftConfig = DEFAULT_SHIFT_CONFIG) -> ShiftWindow:
    """给定时刻属于哪个班次。

    凌晨（早于白班开始）属于**前一天**的晚班 —— 这是归属规则的关键分支。
    """
    if dt.hour < cfg.day_start_hour:
        return shift_bounds(dt.date() - timedelta(days=1), SHIFT_NIGHT, cfg)
    if dt.hour < cfg.night_start_hour:
        return shift_bounds(dt.date(), SHIFT_DAY, cfg)
    return shift_bounds(dt.date(), SHIFT_NIGHT, cfg)


def current_shift(cfg: ShiftConfig = DEFAULT_SHIFT_CONFIG,
                  now: Optional[datetime] = None) -> ShiftWindow:
    """当前正在进行的班次。"""
    return shift_of(now or datetime.now(), cfg)


def full_day_of(dt: datetime, cfg: ShiftConfig = DEFAULT_SHIFT_CONFIG) -> ShiftWindow:
    """给定时刻所属的"天"窗口（06:00 起算，早于 day_start_hour 归前一天）。"""
    day = dt.date() if dt.hour >= cfg.day_start_hour else dt.date() - timedelta(days=1)
    return full_day_bounds(day, cfg)


def shifts_in_range(start: datetime, end: datetime,
                    cfg: ShiftConfig = DEFAULT_SHIFT_CONFIG,
                    clip: bool = True) -> List[ShiftWindow]:
    """时间范围覆盖到的所有班次，按时间升序。

    clip=True（默认）把首尾班次裁剪到 [start, end] 内 —— 用户选的范围
    通常不会正好卡在班次边界上，裁剪后各班次指标按实际覆盖范围算，
    并可通过 is_partial 标出"这个班次数据不完整"。
    clip=False 则返回完整班次窗口（用于"把范围扩展到整班"的场景）。
    """
    if end <= start:
        return []
    out: List[ShiftWindow] = []
    cur = shift_of(start, cfg)
    while cur.start < end:
        w = cur.clip(start, end) if clip else cur
        if w is not None:
            out.append(w)
        # 下一个班次：从当前班次结束时刻往后推 1 秒定位，避免边界时刻归错班
        nxt = shift_of(cur.end + timedelta(seconds=1), cfg)
        if nxt.start <= cur.start:      # 防御：配置异常时不至于死循环
            break
        cur = nxt
    return out


def full_days_in_range(start: datetime, end: datetime,
                       cfg: ShiftConfig = DEFAULT_SHIFT_CONFIG,
                       clip: bool = True) -> List[ShiftWindow]:
    """时间范围覆盖到的所有"天"窗口(06:00→次日06:00)，按时间升序。

    与 shifts_in_range() 同构，只是以 24 小时(而不是 12 小时班次)为步进单位——
    浏览 3 天/1 个月这种跨度较大的范围时，用天粒度而不是班次粒度取已存结果，
    行数少一半，且掐头去尾是按天独立算的，不等于把两个班次的结果简单相加。
    """
    if end <= start:
        return []
    out: List[ShiftWindow] = []
    cur = full_day_of(start, cfg)
    while cur.start < end:
        w = cur.clip(start, end) if clip else cur
        if w is not None:
            out.append(w)
        nxt = full_day_of(cur.end + timedelta(seconds=1), cfg)
        if nxt.start <= cur.start:      # 防御：配置异常时不至于死循环
            break
        cur = nxt
    return out


def parse_shift_key(key: str, cfg: ShiftConfig = DEFAULT_SHIFT_CONFIG) -> ShiftWindow:
    """从 20260803-night 这样的键还原班次窗口(也支持 20260803-full 天粒度键)。"""
    try:
        d_str, s_type = key.split("-", 1)
        d = datetime.strptime(d_str, "%Y%m%d").date()
    except (ValueError, AttributeError) as e:
        raise ValueError(f"班次键格式错误: {key}") from e
    if s_type not in (SHIFT_DAY, SHIFT_NIGHT, SHIFT_FULL):
        raise ValueError(f"未知班次类型: {s_type}")
    if s_type == SHIFT_FULL:
        return full_day_bounds(d, cfg)
    return shift_bounds(d, s_type, cfg)
