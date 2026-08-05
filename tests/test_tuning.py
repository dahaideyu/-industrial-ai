"""Unit tests for backend/modules/device_param/tuning.py

调参配置的纯逻辑部分（_coerce / validate / schema）不需要数据库，
这些函数是工艺人员通过 UI 调阈值时的安全边界——越界值必须被夹到边界，
类型错误必须回退到默认值，不能让一个手滑把 0.5 变成 5 然后所有参数都被认成脉冲。

测试覆盖：
- _coerce: 类型转换 + 越界夹值
- validate: 未知键丢弃 + None 恢复默认 + 越界夹值
- schema: 前端表单定义完整性
- DEFAULTS: 所有默认值在合法范围内
"""
import pytest

from backend.modules.device_param import tuning
from backend.modules.device_param.tuning import DEFAULTS, _coerce, validate, schema


class TestCoerce:
    def test_float_within_bounds(self):
        assert _coerce("pulse_step_score", 0.7) == 0.7

    def test_float_below_min_clamped(self):
        """越界值夹到下限"""
        assert _coerce("pulse_step_score", -0.5) == 0.0

    def test_float_above_max_clamped(self):
        """越界值夹到上限"""
        assert _coerce("pulse_step_score", 1.5) == 1.0

    def test_int_within_bounds(self):
        assert _coerce("pulse_min_points", 200) == 200

    def test_int_below_min_clamped(self):
        assert _coerce("pulse_min_points", 1) == 10

    def test_int_above_max_clamped(self):
        assert _coerce("pulse_min_points", 999999) == 100000

    def test_string_coerced_to_float(self):
        """字符串 '0.8' 应被转为 float"""
        assert _coerce("pulse_step_score", "0.8") == 0.8

    def test_invalid_string_falls_back_to_default(self):
        """无法解析的值回退到默认值"""
        assert _coerce("pulse_step_score", "abc") == DEFAULTS["pulse_step_score"]

    def test_none_falls_back_to_default(self):
        assert _coerce("pulse_step_score", None) == DEFAULTS["pulse_step_score"]


class TestValidate:
    def test_valid_overrides_kept(self):
        overrides = {"pulse_step_score": 0.7, "pulse_min_points": 200}
        clean, ignored = validate(overrides)
        assert clean["pulse_step_score"] == 0.7
        assert clean["pulse_min_points"] == 200
        assert ignored == []

    def test_unknown_keys_ignored(self):
        overrides = {"pulse_step_score": 0.7, "unknown_key": 123}
        clean, ignored = validate(overrides)
        assert "unknown_key" not in clean
        assert "unknown_key" in ignored

    def test_none_means_remove(self):
        """None 值表示恢复默认，不在 clean 中出现"""
        overrides = {"pulse_step_score": None}
        clean, ignored = validate(overrides)
        assert "pulse_step_score" not in clean

    def test_out_of_bounds_clamped(self):
        overrides = {"pulse_step_score": 99.0}
        clean, _ = validate(overrides)
        assert clean["pulse_step_score"] == 1.0  # 夹到上限

    def test_empty_overrides(self):
        clean, ignored = validate({})
        assert clean == {}
        assert ignored == []

    def test_none_overrides(self):
        clean, ignored = validate(None)
        assert clean == {}
        assert ignored == []


class TestSchema:
    def test_schema_has_all_keys(self):
        """schema 必须覆盖 DEFAULTS 中的所有键"""
        sch = schema()
        schema_keys = {item["key"] for item in sch}
        assert schema_keys == set(DEFAULTS.keys())

    def test_schema_items_have_required_fields(self):
        """每项必须有 key/default/type/label/desc/min/max"""
        sch = schema()
        for item in sch:
            assert "key" in item
            assert "default" in item
            assert "type" in item
            assert "label" in item
            assert "desc" in item
            assert "min" in item
            assert "max" in item

    def test_defaults_within_bounds(self):
        """所有默认值必须在 [min, max] 范围内"""
        sch = schema()
        for item in sch:
            d = item["default"]
            assert item["min"] <= d <= item["max"], \
                f"{item['key']} 默认值 {d} 不在 [{item['min']}, {item['max']}] 范围内"


class TestDefaults:
    def test_defaults_not_empty(self):
        assert len(DEFAULTS) >= 10

    def test_all_defaults_are_correct_types(self):
        """int 类型的默认值必须是 int，float 类型的必须是 float"""
        from backend.modules.device_param.tuning import _TYPES
        for key, value in DEFAULTS.items():
            expected_type = _TYPES[key]
            assert isinstance(value, expected_type), \
                f"{key} 默认值类型应为 {expected_type.__name__}，实际是 {type(value).__name__}"
