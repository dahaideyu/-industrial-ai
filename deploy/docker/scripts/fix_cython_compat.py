#!/usr/bin/env python3
"""
修复 Python 3.10+ 类型注解语法，确保 Cython 兼容性。

Cython 3.x 对 `X | Y` 类型联合语法支持不完善，
需要将 `str | None` 等改为 `Optional[str]`，`str | int` 等改为 `Union[str, int]`。

用法：在 Cython 编译前，WORKDIR 为 /build 时运行：
    python docker/scripts/fix_cython_compat.py
"""
import os
import re
import sys


def _has_typing_import(content: str) -> bool:
    """检查文件是否已有 typing 导入"""
    return "from typing import" in content or "import typing" in content


def _add_imports(content: str, needed: set[str]) -> str:
    """在文件顶部添加缺失的 typing 导入"""
    if not needed:
        return content

    # 构建导入语句
    imports_to_add = sorted(needed)
    import_line = f"from typing import {', '.join(imports_to_add)}"

    # 检查是否已有部分导入，合并
    match = re.match(r"^(from typing import )(.+)$", content, re.MULTILINE)
    if match:
        existing_imports = set(
            name.strip() for name in match.group(2).split(",")
        )
        all_imports = existing_imports | needed
        new_import_line = f"from typing import {', '.join(sorted(all_imports))}"
        content = content.replace(match.group(0), new_import_line, 1)
    else:
        # 在文件顶部、第一个 import 之前插入
        lines = content.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                insert_idx = i
                break
            # 跳过 shebang、编码声明、docstring
            if stripped.startswith("#!") or stripped.startswith("# -*-") or stripped == '"""':
                continue
        lines.insert(insert_idx, import_line)
        content = "\n".join(lines)

    return content


def _replace_union_syntax(content: str) -> tuple[str, set[str]]:
    """
    替换所有 X | Y 类型联合语法为对应的 typing 形式。
    返回 (修改后的内容, 需要的 typing 导入集合)
    """
    needed_imports = set()

    # 模式 1: X | None -> Optional[X]（支持嵌套括号如 list[str] | None）
    def _replace_none_unions(text: str) -> str:
        result = []
        i = 0
        while i < len(text):
            # 查找 | None 模式
            if text[i] == '|' and text[i:].lstrip().startswith('None'):
                # 向前找到完整的类型表达式
                j = i - 1
                # 跳过空格
                while j >= 0 and text[j] == ' ':
                    j -= 1
                # 从 j 向前找到表达式起始（处理嵌套括号）
                bracket_depth = 0
                end = j
                while j >= 0:
                    if text[j] in ')]}':
                        bracket_depth += 1
                    elif text[j] in '([{':
                        bracket_depth -= 1
                    if bracket_depth < 0 or (bracket_depth == 0 and text[j] in ' ,\t\n=('):
                        j += 1
                        break
                    j -= 1
                else:
                    j = 0
                type_expr = text[j:end+1].strip()
                # 跳过 | None
                k = i + 1
                while k < len(text) and text[k] in ' \t':
                    k += 1
                k += 4  # len("None")
                # 检查后面是否还有 | None 链
                remaining = text[k:].lstrip()
                if remaining.startswith('|') and 'None' in remaining[:20]:
                    # X | None | None 等情况，继续处理
                    pass
                needed_imports.add("Optional")
                result.append(f"Optional[{type_expr}]")
                i = k
            else:
                result.append(text[i])
                i += 1
        return ''.join(result)

    content = _replace_none_unions(content)

    # 模式 1b: None | X -> Optional[X]
    content = re.sub(
        r"\bNone\s*\|\s*([\w\[\(\"'])",
        lambda m: (needed_imports.add("Optional"), f"Optional[{m.group(1)}]")[1],
        content
    )

    # 模式 2: X | Y (非 None 联合) -> Union[X, Y]
    # 只处理类型注解上下文（: X | Y 或 -> X | Y）
    def replace_union_in_annotation(match):
        prefix = match.group(1)  # : 或 ->
        types_str = match.group(2).strip()
        types = [t.strip() for t in types_str.split("|")]
        if len(types) >= 2 and "None" not in types:
            needed_imports.add("Union")
            return f"{prefix} Union[{', '.join(types)}]"
        return match.group(0)

    content = re.sub(
        r"(:\s*)(\w[\w\[\], ]*(?:\s*\|\s*\w[\w\[\], ]*)+)(?=\s*[=,)\]])",
        replace_union_in_annotation,
        content
    )

    # 模式 3: Mapped[X | None] -> Mapped[Optional[X]]
    # 已被模式 1 覆盖

    return content, needed_imports


def _convert_fstrings(content: str) -> str:
    """
    将多行 f-string (f\"\"\"...\"\"\") 和包含复杂表达式的 f-string 转为 .format()。
    Cython 3.x 对 f-string 的 UnicodeNode 处理有 bug，会导致编译失败。
    """
    # 模式 1: 多行 f-string sql = f"""..."""
    # 将 f"""...{expr}...""" 替换为 """...{}...""".format(expr)
    def replace_multiline_fstring(match):
        prefix = match.group(1)  # 变量赋值部分，如 "    sql = "
        body = match.group(2)    # f-string 内容
        # 提取所有 {expr} 表达式
        exprs = []
        result = body
        # 匹配 {expr}，但不匹配 {{ 或 }}
        i = 0
        new_body_parts = []
        while i < len(result):
            # f-string 转义 {{ → 原样保留 {{（.format() 也使用 {{ 表字面量 {）
            if result[i] == '{' and i + 1 < len(result) and result[i+1] == '{':
                new_body_parts.append('{{')
                i += 2
            # f-string 转义 }} → 原样保留 }}（.format() 也使用 }} 表字面量 }）
            elif result[i] == '}' and i + 1 < len(result) and result[i+1] == '}':
                new_body_parts.append('}}')
                i += 2
            # 格式表达式: {expr}
            elif result[i] == '{':
                # 找到匹配的 }（跟踪括号和引号深度）
                depth = 1
                in_quote = None  # 当前在哪个引号内
                j = i + 1
                while j < len(result) and depth > 0:
                    ch = result[j]
                    # 处理引号状态
                    if in_quote is None:
                        if ch in ('"', "'"):
                            in_quote = ch
                        elif ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                    elif ch == in_quote:
                        # 检查是否转义
                        if j > 0 and result[j-1] == '\\':
                            pass
                        else:
                            in_quote = None
                    j += 1
                expr = result[i+1:j-1].strip()
                # 跳过格式说明符（如 :.4f）——只在顶层括号外找冒号
                paren_depth = 0
                in_quote_fmt = None
                fmt_idx = len(expr)
                for k, ch in enumerate(expr):
                    if in_quote_fmt is None:
                        if ch in ('"', "'"):
                            in_quote_fmt = ch
                        elif ch in '([':
                            paren_depth += 1
                        elif ch in ')]':
                            paren_depth -= 1
                        elif ch == ':' and paren_depth == 0:
                            fmt_idx = k
                            break
                    elif ch == in_quote_fmt:
                        if k > 0 and expr[k-1] == '\\':
                            pass
                        else:
                            in_quote_fmt = None
                expr_base = expr[:fmt_idx].strip()
                exprs.append(expr_base)
                new_body_parts.append("{}")
                i = j
            else:
                new_body_parts.append(result[i])
                i += 1
        new_body = "".join(new_body_parts)
        if not exprs:
            return match.group(0)
        exprs_str = ", ".join(exprs)
        return f'{prefix}"""{new_body}""".format({exprs_str})'

    # 匹配多行 f-string（变量赋值 或 return 语句）
    content = re.sub(
        r'^(\s*(?:\w+\s*=\s*|return\s+))f"""(.*?)"""',
        replace_multiline_fstring,
        content,
        flags=re.MULTILINE | re.DOTALL
    )

    # 模式 2: 单行 f-string 中包含 .join() 调用
    # f"...{', '.join(x)}..." -> "...{}...".format(', '.join(x))
    def replace_join_fstring(match):
        full = match.group(0)
        # 提取引号类型
        quote = full[1]  # " 或 '
        # 找到 f 和引号后的内容
        start_idx = full.index(quote) + 1
        end_idx = full.rindex(quote)
        body = full[start_idx:end_idx]
        # 提取 .join() 表达式
        exprs = []
        result = body
        i = 0
        new_parts = []
        while i < len(result):
            if result[i] == '{' and i + 1 < len(result) and result[i+1] == '{':
                new_parts.append('{{')
                i += 2
            elif result[i] == '}' and i + 1 < len(result) and result[i+1] == '}':
                new_parts.append('}}')
                i += 2
            elif result[i] == '{':
                depth = 1
                j = i + 1
                while j < len(result) and depth > 0:
                    if result[j] == '{':
                        depth += 1
                    elif result[j] == '}':
                        depth -= 1
                    j += 1
                expr = result[i+1:j-1].strip()
                exprs.append(expr)
                new_parts.append("{}")
                i = j
            else:
                new_parts.append(result[i])
                i += 1
        new_body = "".join(new_parts)
        if not exprs:
            return full
        exprs_str = ", ".join(exprs)
        return f'{quote}{new_body}{quote}.format({exprs_str})'

    # 匹配包含 .join 的单行 f-string
    content = re.sub(
        r'''f(["'])((?:(?!\1).)*\.join\((?:(?!\1).)*\{.*?\}.*?)*?\1''',
        replace_join_fstring,
        content
    )

    return content


def fix_file(filepath: str) -> bool:
    """
    修复单个文件的 Cython 兼容性。
    返回 True 表示文件被修改。
    """
    with open(filepath, "r", encoding="utf-8") as f:
        original = f.read()

    content = original

    # 0. 添加 Cython 指令（必须在文件最开头）
    # annotation_typing=False: 禁止用函数注解做 C 类型声明（FastAPI 的 Query/Header 会冲突）
    # infer_types=False: 禁止类型推断（避免 pandas 链式索引被误认为 memoryview）
    # language_level=3: 使用 Python 3 语义
    cython_directive = "# cython: annotation_typing=False, infer_types=False, language_level=3\n"
    if "# cython:" not in content.split("\n")[0]:
        content = cython_directive + content

    # 1. 移除 from __future__ import annotations（Cython 不支持）
    if "from __future__ import annotations" in content:
        content = content.replace("from __future__ import annotations\n", "")
        content = content.replace("from __future__ import annotations", "")

    # 2. 修复类型注解
    has_union = bool(re.search(r"\w\s*\|\s*\w", content))
    if has_union:
        content, needed_imports = _replace_union_syntax(content)
        if needed_imports and ("Optional" in content or "Union" in content):
            content = _add_imports(content, needed_imports)

    # 3. 转换多行 f-string（Cython UnicodeNode bug）
    if 'f"""' in content:
        content = _convert_fstrings(content)

    if content == original:
        return False

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return True


def main():
    """修复 backend/ 目录下所有 Python 文件的类型注解"""
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "backend"
    print(f"=== 开始修复类型注解 (目标: {target_dir}) ===")

    fixed_count = 0
    for root, dirs, files in os.walk(target_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            filepath = os.path.join(root, fname)
            try:
                if fix_file(filepath):
                    print(f"  已修复: {filepath}")
                    fixed_count += 1
            except Exception as e:
                print(f"  警告: 修复 {filepath} 失败: {e}")

    print(f"=== 类型注解修复完成，共修复 {fixed_count} 个文件 ===")


if __name__ == "__main__":
    main()
