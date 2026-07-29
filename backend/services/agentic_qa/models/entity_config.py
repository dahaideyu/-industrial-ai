# cython: annotation_typing=False, infer_types=False, language_level=3
import json
import re

from sqlalchemy import String, Integer, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.core.agentic_qa.database import Base

# table_name/label_column/value_column/search_columns/context_columns 和
# filter_condition 会被 entity_resolver 直接拼进 f-string SQL 执行（标识符没法走
# 参数化占位符），这几个字段又是这个 /admin 接口可写的——不校验的话相当于让能调
# 这个接口的人拼任意 SQL。下面两个校验函数在写入（admin.py）和使用
# （entity_resolver.py）两端都会调用，双重兜底。
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# filter_condition 本质是"管理员可配置的原始 WHERE 片段"，没法做到 100% 安全校验
# （比如合法的 "OR" 连接词没法跟注入区分开），这里只收紧最明确的攻击手段：
# 分号叠加语句、--/#/\/* 注释截断、反引号逃逸标识符
_FILTER_CONDITION_ALLOWED_RE = re.compile(r"^[A-Za-z0-9_.,()'\"=<>!\s]*$")


def validate_identifier(name: str, field_name: str) -> str:
    """校验表名/列名：只允许字母数字下划线，防止拼进 SQL 时逃逸出标识符。"""
    if not name or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"{field_name} 只能包含字母、数字、下划线，且不能以数字开头：{name!r}")
    return name


def validate_filter_condition(condition: str) -> str:
    """校验 filter_condition：禁止分号/注释符/反引号等常见 SQL 注入手法。"""
    if condition is None:
        return condition
    if not _FILTER_CONDITION_ALLOWED_RE.match(condition):
        raise ValueError(f"filter_condition 包含不允许的字符（禁止分号、注释符、反引号等）：{condition!r}")
    return condition


class EntityConfig(Base):
    __tablename__ = "entity_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    search_columns: Mapped[str] = mapped_column(Text, nullable=False, default="[]")       # JSON array
    label_column: Mapped[str] = mapped_column(String(64), nullable=False, default="name")
    value_column: Mapped[str] = mapped_column(String(64), nullable=False, default="id")
    context_columns: Mapped[str] = mapped_column(Text, nullable=False, default="[]")       # JSON array
    keyword_hints: Mapped[str] = mapped_column(Text, nullable=False, default="[]")         # JSON array
    filter_condition: Mapped[str] = mapped_column(Text, nullable=False, default="del_flag = 0")
    is_indexed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_dict(self):
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "label": self.label,
            "table_name": self.table_name,
            "search_columns": _json_loads(self.search_columns),
            "label_column": self.label_column,
            "value_column": self.value_column,
            "context_columns": _json_loads(self.context_columns),
            "keyword_hints": _json_loads(self.keyword_hints),
            "filter_condition": self.filter_condition,
            "is_indexed": self.is_indexed,
        }

    def to_registry_entry(self) -> dict:
        """转换为 entity_resolver 兼容的注册表条目格式"""
        return {
            "label": self.label,
            "table": self.table_name,
            "search_columns": _json_loads(self.search_columns),
            "label_column": self.label_column,
            "value_column": self.value_column,
            "context_columns": _json_loads(self.context_columns),
            "keyword_hints": _json_loads(self.keyword_hints),
            "filter_condition": self.filter_condition,
        }


def _json_loads(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return []


def migrate_default_configs(db_session):
    """自动迁移硬编码的默认实体配置到数据库"""
    from sqlalchemy import text
    defaults = [
        {
            "entity_type": "production_line",
            "label": "产线",
            "table_name": "sys_line",
            "search_columns": ["name"],
            "label_column": "name",
            "value_column": "id",
            "context_columns": ["type"],
            "keyword_hints": ["产线", "线", "车间", "线体", "生产线"],
            "filter_condition": "del_flag = 0",
        },
        {
            "entity_type": "device",
            "label": "设备",
            "table_name": "dev_device",
            "search_columns": ["name", "short_no"],
            "label_column": "name",
            "value_column": "id",
            "context_columns": ["device_type", "factory", "status", "position"],
            "keyword_hints": ["设备", "机", "仪", "装置"],
            "filter_condition": "del_flag = 0",
        },
    ]
    for d in defaults:
        existing = db_session.query(EntityConfig).filter(EntityConfig.entity_type == d["entity_type"]).first()
        if not existing:
            cfg = EntityConfig(
                entity_type=d["entity_type"],
                label=d["label"],
                table_name=d["table_name"],
                search_columns=json.dumps(d["search_columns"], ensure_ascii=False),
                label_column=d["label_column"],
                value_column=d["value_column"],
                context_columns=json.dumps(d["context_columns"], ensure_ascii=False),
                keyword_hints=json.dumps(d["keyword_hints"], ensure_ascii=False),
                is_indexed=False,
            )
            db_session.add(cfg)
    db_session.commit()
