"""Unit tests for backend/modules/device_param/shift.py

班次窗口计算是设备分析的核心基础：班次归属、时间范围拆分、
缓存键生成等逻辑一旦出错，分析结果会落到错误的班次上。

测试覆盖：
- shift_of: 任意时刻→所属班次（含凌晨归属前日晚班的关键边界）
- shift_bounds: 班次窗口的起止时刻
- shifts_in_range: 时间范围→班次列表（含裁剪）
- parse_shift_key: 缓存键↔窗口互转
- ShiftWindow 属性: key/label/hours/is_closed/is_partial
"""
import pytest
from datetime import datetime, date, timedelta

from backend.modules.device_param.shift import (
    SHIFT_DAY, SHIFT_NIGHT,
    ShiftConfig, ShiftWindow,
    shift_bounds, shift_of, current_shift,
    shifts_in_range, parse_shift_key,
)


class TestShiftOf:
    """shift_of 是整个班次体系的核心：给定时刻→归属哪个班次。"""

    def test_morning_belongs_to_day(self):
        """上午 10:00 属于当天白班"""
        dt = datetime(2026, 8, 3, 10, 0, 0)
        w = shift_of(dt)
        assert w.shift_type == SHIFT_DAY
        assert w.shift_date == date(2026, 8, 3)

    def test_afternoon_belongs_to_day(self):
        """下午 17:59 仍属于当天白班（白班到 18:00 结束）"""
        dt = datetime(2026, 8, 3, 17, 59, 59)
        w = shift_of(dt)
        assert w.shift_type == SHIFT_DAY
        assert w.shift_date == date(2026, 8, 3)

    def test_evening_belongs_to_night(self):
        """晚上 19:00 属于当天晚班"""
        dt = datetime(2026, 8, 3, 19, 0, 0)
        w = shift_of(dt)
        assert w.shift_type == SHIFT_NIGHT
        assert w.shift_date == date(2026, 8, 3)

    def test_early_morning_belongs_to_previous_night(self):
        """凌晨 03:00 属于**前一天**的晚班——这是现场交接班口径"""
        dt = datetime(2026, 8, 4, 3, 0, 0)
        w = shift_of(dt)
        assert w.shift_type == SHIFT_NIGHT
        assert w.shift_date == date(2026, 8, 3), "凌晨应归属前一天的晚班"

    def test_boundary_day_start(self):
        """06:00:00 恰好是白班开始"""
        dt = datetime(2026, 8, 3, 6, 0, 0)
        w = shift_of(dt)
        assert w.shift_type == SHIFT_DAY

    def test_boundary_night_start(self):
        """18:00:00 恰好是晚班开始"""
        dt = datetime(2026, 8, 3, 18, 0, 0)
        w = shift_of(dt)
        assert w.shift_type == SHIFT_NIGHT

    def test_custom_config(self):
        """三班倒配置：每班 8 小时"""
        cfg = ShiftConfig(day_start_hour=6, shift_hours=8)
        # 13:00 在 06:00-14:00 之间属于第一班（day）
        dt = datetime(2026, 8, 3, 13, 0, 0)
        w = shift_of(dt, cfg)
        assert w.shift_type == SHIFT_DAY
        assert w.hours == 8.0


class TestShiftBounds:
    def test_day_shift_window(self):
        """白班：06:00-18:00"""
        w = shift_bounds(date(2026, 8, 3), SHIFT_DAY)
        assert w.start == datetime(2026, 8, 3, 6, 0, 0)
        assert w.end == datetime(2026, 8, 3, 18, 0, 0)
        assert w.hours == 12.0

    def test_night_shift_window_crosses_midnight(self):
        """晚班：18:00-次日06:00（跨天）"""
        w = shift_bounds(date(2026, 8, 3), SHIFT_NIGHT)
        assert w.start == datetime(2026, 8, 3, 18, 0, 0)
        assert w.end == datetime(2026, 8, 4, 6, 0, 0)
        assert w.hours == 12.0

    def test_invalid_shift_type(self):
        with pytest.raises(ValueError, match="未知班次类型"):
            shift_bounds(date(2026, 8, 3), "invalid")


class TestShiftsInRange:
    def test_single_day_shifts(self):
        """06:00-23:59 覆盖白班+晚班两个班次（从白班开始时间起算）"""
        start = datetime(2026, 8, 3, 6, 0, 0)
        end = datetime(2026, 8, 3, 23, 59, 59)
        shifts = shifts_in_range(start, end)
        assert len(shifts) == 2
        assert shifts[0].shift_type == SHIFT_DAY
        assert shifts[1].shift_type == SHIFT_NIGHT

    def test_partial_shifts_at_boundaries(self):
        """裁剪后首尾班次标记为 partial"""
        # 10:00-20:00 覆盖白班后半段和晚班前半段
        start = datetime(2026, 8, 3, 10, 0, 0)
        end = datetime(2026, 8, 3, 20, 0, 0)
        shifts = shifts_in_range(start, end, clip=True)
        assert len(shifts) == 2
        assert shifts[0].is_partial, "白班被裁剪了前4小时"
        assert shifts[1].is_partial, "晚班被裁剪了后10小时"

    def test_full_shifts_not_partial(self):
        """不裁剪时返回完整班次窗口"""
        start = datetime(2026, 8, 3, 10, 0, 0)
        end = datetime(2026, 8, 3, 20, 0, 0)
        shifts = shifts_in_range(start, end, clip=False)
        for s in shifts:
            assert not s.is_partial

    def test_empty_range(self):
        """start >= end 返回空列表"""
        start = datetime(2026, 8, 3, 12, 0, 0)
        assert shifts_in_range(start, start) == []

    def test_multi_day_range(self):
        """3天覆盖6个班次（3白+3晚）"""
        start = datetime(2026, 8, 3, 6, 0, 0)
        end = datetime(2026, 8, 6, 6, 0, 0)
        shifts = shifts_in_range(start, end)
        assert len(shifts) == 6

    def test_sorted_chronologically(self):
        """结果按时间升序"""
        start = datetime(2026, 8, 3, 0, 0, 0)
        end = datetime(2026, 8, 4, 0, 0, 0)
        shifts = shifts_in_range(start, end)
        for i in range(len(shifts) - 1):
            assert shifts[i].start < shifts[i + 1].start


class TestParseShiftKey:
    def test_roundtrip(self):
        """shift_bounds → key → parse_shift_key 应能还原"""
        original = shift_bounds(date(2026, 8, 3), SHIFT_NIGHT)
        parsed = parse_shift_key(original.key)
        assert parsed.start == original.start
        assert parsed.end == original.end
        assert parsed.shift_type == SHIFT_NIGHT

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="班次键格式错误"):
            parse_shift_key("invalid-key")

    def test_invalid_shift_type(self):
        with pytest.raises(ValueError, match="未知班次类型"):
            parse_shift_key("20260803-noon")


class TestShiftWindowProperties:
    def test_key_format(self):
        w = shift_bounds(date(2026, 8, 3), SHIFT_DAY)
        assert w.key == "20260803-day"

    def test_label(self):
        w = shift_bounds(date(2026, 8, 3), SHIFT_NIGHT)
        assert "晚班" in w.label
        assert "08-03" in w.label

    def test_is_closed_past(self):
        """已结束的班次 is_closed=True"""
        w = shift_bounds(date(2026, 1, 1), SHIFT_DAY)
        assert w.is_closed(now=datetime(2026, 8, 3, 12, 0, 0))

    def test_is_closed_future(self):
        """未结束的班次 is_closed=False"""
        future = datetime.now() + timedelta(days=1)
        w = shift_bounds(future.date(), SHIFT_DAY)
        assert not w.is_closed()

    def test_clip_disjoint(self):
        """完全不相交返回 None"""
        w = shift_bounds(date(2026, 8, 3), SHIFT_DAY)
        result = w.clip(datetime(2026, 9, 1), datetime(2026, 9, 2))
        assert result is None

    def test_clip_partial(self):
        """裁剪到子区间"""
        w = shift_bounds(date(2026, 8, 3), SHIFT_DAY)
        result = w.clip(
            datetime(2026, 8, 3, 10, 0, 0),
            datetime(2026, 8, 3, 14, 0, 0),
        )
        assert result is not None
        assert result.start == datetime(2026, 8, 3, 10, 0, 0)
        assert result.end == datetime(2026, 8, 3, 14, 0, 0)
        assert result.is_partial

    def test_to_dict(self):
        w = shift_bounds(date(2026, 8, 3), SHIFT_DAY)
        # 用白班结束后的时刻作为 now，确保 is_closed=True
        d = w.to_dict(now=datetime(2026, 8, 3, 19, 0, 0))
        assert d["key"] == "20260803-day"
        assert d["shift_type"] == SHIFT_DAY
        assert d["hours"] == 12.0
        assert d["closed"] is True
        assert d["partial"] is False
