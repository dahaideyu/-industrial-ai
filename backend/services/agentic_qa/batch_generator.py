# cython: annotation_typing=False, infer_types=False, language_level=3
"""AI批量生成SQL问答训练对 — 核心生成逻辑 + 草稿存储"""
import asyncio
import json
import re
import threading
import uuid
import difflib
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from backend.core.agentic_qa.config import settings
from backend.core.agentic_qa.llm import llm
from backend.core.agentic_qa.logger import get_logger
from backend.services.agentic_qa.db.mysql import db as mysql_db
from backend.services.agentic_qa.vanna.guard import validate_sql

logger = get_logger("services.batch_generator")

BATCH_SYSTEM_PROMPT = """你是一个工业数据SQL问答对生成器，专门为工厂的产线主管、设备管理员、车间主任等非技术用户生成训练数据。

## 核心任务
根据表结构、示例数据和业务上下文，理解数据模型后生成自然语言问题和对应的MySQL查询。

## 主题约束（最高优先级）
训练主题限定了问题必须围绕的业务场景。你生成的所有问题都必须**严格属于该主题范围**，不相关的一律不要生成。

例如：
- 主题=设备状态 → 只生成设备运行状态、停机、故障、待机、维修状态相关的问题
  - ✅ "制带线今天有几台设备在运行？"
  - ✅ "最近一周哪些设备故障超过3次？"
  - ❌ "查询所有供应商为XX的设备列表" ← 这是设备供应商管理，不是设备状态
  - ❌ "各产线有多少台设备？" ← 这是设备资产统计，不是设备状态
- 主题=设备维修 → 只生成维修工单、维修时长、维修次数、维修人员相关的问题
- 主题=设备效率 → 只生成OEE、利用率、产能、良率相关的问题

在生成每个问题前，先问自己：这个问题是否直接属于该训练主题？如果不是，跳过。

## 问题风格（非常重要）
你的用户是完全不懂数据库和SQL的工厂人员。问题必须符合以下风格：

1. **像工人在聊天**：使用口语化表达，不是数据库查询语言
   - ✅ 好："制带线今天停机了几次？"
   - ✅ 好："最近一个月哪条产线故障最多？"
   - ✅ 好："3号设备现在的状态是什么？"
   - ❌ 差："查询产线'制带线'中昨天哪些设备发生了异常（exception_count>0）"
   - ❌ 差："统计sys_line表中各产线的dev_device数量"
   - ❌ 差："查询status字段为'故障'且create_time在最近7天的记录"

2. **不透露技术细节**：绝对不能在问题中出现字段名、表名、SQL关键词、运算符
   - 用"停了多久"代替"查询stop_duration"
   - 用"今天"代替"查询create_time >= CURDATE()"
   - 用"故障"代替"查询status = 'fault'"

3. **使用真实实体名**：参考示例数据中的产线名、设备名等真实值
   - ✅ 好："正冲网最近设备状态怎么样"
   - ✅ 好："制带线上个月维修了几次"

4. **简洁直接**：一个问题一句话，15-30字最佳

## 问题类型覆盖
- 简单查询（约20%）：查单个设备/产线的状态或信息
- 时间范围（约20%）：今天/昨天/本周/本月/最近N天的数据
- 统计排名（约20%）：哪条产线最多/最少、TOP排名
- 汇总计数（约20%）：总共几台、停机几次、故障多少
- 关联对比（约20%）：跨产线/跨设备/跨时间段的对比

## SQL质量要求
- 只生成SELECT语句
- 必须包含LIMIT（默认1000，明细10-100）
- 核心表加del_flag=0过滤
- 时间字段加默认30天范围
- 使用实际表名和字段名

## 多问题变体（同一SQL的不同问法）
同一个SQL可以对应多种自然语言问法。为每个SQL提供1个主要问题，再提供1-3个备选问法（alt_questions）。例如：
同一个SQL：SELECT status, COUNT(*) FROM dev_device WHERE line_id=3 GROUP BY status
- 主问题："制带线的设备现在都什么状态？"
- 备选1："制带线有多少设备在运行、多少停了？"
- 备选2："看看制带线设备运行情况"

如果确实没有合理的备选问法，alt_questions可以为空数组。

## 数量原则
- 宁缺毋滥，有价值的场景不够就少生成
- 不要生成仅改变LIMIT值或时间数字的变体

## 输出格式
严格输出JSON数组，不要加说明或markdown标记：
[{"question": "主问题", "alt_questions": ["备选问法1", "备选问法2"], "sql": "SELECT ..."}, ...]"""


class BatchGenerator:
    """AI批量生成SQL问答训练对，管理生成任务和草稿存储"""

    def __init__(self):
        self.jobs: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._drafts_collection = None

    # ======== Draft Collection ========

    def _get_drafts_collection(self):
        """获取或创建 batch_generated_drafts 集合（复用 VannaAgentManager 的 ChromaDB 客户端）"""
        if self._drafts_collection is not None:
            return self._drafts_collection
        from backend.services.agentic_qa.vanna.agent import get_vanna_manager
        manager = get_vanna_manager()
        self._drafts_collection = manager.get_batch_drafts_collection()
        logger.info("[batch_generator] drafts collection ready (via VannaAgentManager)")
        return self._drafts_collection

    # ======== Job Management ========

    def create_job(
        self,
        theme: str,
        table_names: List[str],
        count: int,
        schema_supplement: str = "",
        example_sql: str = "",
    ) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": "pending",
                "theme": theme,
                "table_names": table_names,
                "target_count": count,
                "generated": 0,
                "saved": 0,
                "errors": [],
                "started_at": None,
                "finished_at": None,
                "schema_supplement": schema_supplement,
                "example_sql": example_sql,
            }
        logger.info(f"[batch_generator] job created: {job_id} theme='{theme}' tables={table_names} count={count}")
        return job_id

    def get_job_status(self, job_id: str) -> dict:
        with self._lock:
            job = self.jobs.get(job_id)
        if job is None:
            return {"success": False, "error": "任务不存在或已过期"}
        return {"success": True, **job}

    def _update_job(self, job_id: str, **kwargs):
        with self._lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(kwargs)

    # ======== Main Flow ========

    async def run_job(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job:
            logger.error(f"[batch_generator] job {job_id} not found")
            return

        self._update_job(job_id, status="running", started_at=datetime.now(timezone.utc).isoformat())
        theme = job["theme"]
        table_names = job["table_names"]
        target_count = job["target_count"]
        schema_supplement = job.get("schema_supplement", "")
        example_sql = job.get("example_sql", "")

        try:
            # 1. 获取表信息
            tables_info = await self._fetch_table_info(table_names)
            if not tables_info:
                self._update_job(job_id, status="failed", errors=["无法获取表结构信息"])
                return

            # 2. 检索已有问答对（用于去重和风格参考）
            existing_questions = await self._get_existing_questions(theme)

            # 3. 构建基础 User Prompt
            base_prompt = self._build_base_prompt(theme, tables_info, schema_supplement, example_sql)

            # 4. 分批生成
            all_entries = []
            remaining = target_count
            batch_num = 0
            max_batches = 20  # 安全上限

            while remaining > 0 and batch_num < max_batches:
                batch_num += 1
                batch_size = min(20, remaining)

                # 追加已生成问题的避重提示
                existing_warning = ""
                if all_entries:
                    existing_questions_list = [e["question"] for e in all_entries]
                    existing_warning = (
                        f"\n\n## 注意：以下问题已生成，请避开这些模式，生成不同角度的问题：\n"
                        + "\n".join(f"- {q}" for q in existing_questions_list[-20:])
                    )

                user_prompt = base_prompt + f"\n\n## 任务\n请生成 {batch_size} 条问题-SQL训练对。{existing_warning}"

                entries = await self._generate_batch(user_prompt, batch_size)
                if not entries:
                    logger.warning(f"[batch_generator] batch {batch_num} returned empty, stopping")
                    break

                # 去重 + 校验 + 保存
                saved_count = 0
                for entry in entries:
                    question = (entry.get("question") or "").strip()
                    sql_text = (entry.get("sql") or "").strip()
                    alt_questions_raw = entry.get("alt_questions") or entry.get("altQuestions") or []
                    alt_questions = [a.strip() for a in alt_questions_raw if isinstance(a, str) and a.strip()]
                    if not question or not sql_text:
                        continue

                    # 重复检测（主问题 + 备选问题都检测）
                    all_qs = [question] + alt_questions
                    if any(self._is_duplicate(q, existing_questions, all_entries) for q in all_qs):
                        continue

                    # SQL 安全校验
                    is_safe, sql_checked = validate_sql(sql_text)
                    if not is_safe:
                        self._add_error(job_id, f"SQL安全检查不通过: {question[:50]}")
                        continue

                    # 保存到草稿库
                    draft_id = self._save_draft(
                        theme=theme,
                        batch_id=job_id,
                        question=question,
                        sql=sql_checked,
                        tables=table_names,
                        alt_questions=alt_questions,
                    )
                    if draft_id:
                        all_entries.append({"question": question, "sql": sql_checked, "draft_id": draft_id, "alt_questions": alt_questions})
                        existing_questions.add(question)
                        for aq in alt_questions:
                            existing_questions.add(aq)
                        saved_count += 1
                    else:
                        self._add_error(job_id, f"保存草稿失败: {question[:50]}")

                remaining = target_count - len(all_entries)
                self._update_job(job_id, generated=len(all_entries), saved=saved_count + job.get("saved", 0))

                # 如果上一批生成质量差（实际生成数远小于请求数），提前终止
                if len(entries) < batch_size * 0.3:
                    logger.info(f"[batch_generator] quality threshold reached, stopping at {len(all_entries)} entries")
                    break

                if remaining > 0:
                    await asyncio.sleep(0.3)

            self._update_job(
                job_id,
                status="done",
                generated=len(all_entries),
                saved=job.get("saved", 0) + len(all_entries),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            logger.info(f"[batch_generator] job {job_id} done: {len(all_entries)} entries generated")

        except Exception as e:
            logger.exception(f"[batch_generator] job {job_id} failed: {e}")
            self._update_job(job_id, status="failed", errors=job.get("errors", []) + [str(e)])

    def _add_error(self, job_id: str, msg: str):
        with self._lock:
            if job_id in self.jobs:
                self.jobs[job_id].setdefault("errors", []).append(msg)

    # ======== Table Info ========

    async def _fetch_table_info(self, table_names: List[str]) -> str:
        """获取表DDL + 列信息 + 表注释 + 示例数据"""
        parts = []
        for t in table_names:
            try:
                t = t.strip()
                if not t:
                    continue

                # DDL
                ddl_rows = mysql_db.execute_query(f"SHOW CREATE TABLE `{t}`")
                ddl = ddl_rows[0].get("Create Table", "") if ddl_rows else ""

                # 表注释
                status_rows = mysql_db.execute_query(f"SHOW TABLE STATUS WHERE Name='{t}'")
                table_comment = ""
                if status_rows:
                    table_comment = status_rows[0].get("Comment", "") or ""

                # 列信息
                col_rows = mysql_db.execute_query(f"DESCRIBE `{t}`")

                # 示例数据
                sample_rows = mysql_db.execute_query(f"SELECT * FROM `{t}` LIMIT 5")

                # 拼接
                header = f"## 表：{t}"
                if table_comment:
                    header += f"（{table_comment}）"

                lines = [header, "", "### DDL", "```sql", ddl, "```", "", "### 列说明"]

                if col_rows:
                    col_header = "| 列名 | 类型 | 是否为空 | 键 | 默认值 | 注释 |"
                    col_sep = "|------|------|---------|----|-------|------|"
                    lines.extend(["", col_header, col_sep])
                    for c in col_rows:
                        lines.append(
                            f"| {c.get('Field', '')} | {c.get('Type', '')} | "
                            f"{c.get('Null', '')} | {c.get('Key', '')} | "
                            f"{c.get('Default', '')} | {c.get('Extra', '')} |"
                        )

                if sample_rows:
                    lines.extend(["", "### 示例数据（前5行）", ""])
                    # 表头
                    keys = list(sample_rows[0].keys())
                    lines.append("| " + " | ".join(keys) + " |")
                    lines.append("|" + "|".join(["------"] * len(keys)) + "|")
                    for row in sample_rows:
                        vals = [str(row.get(k, "")) for k in keys]
                        lines.append("| " + " | ".join(vals) + " |")

                parts.append("\n".join(lines))
            except Exception as e:
                logger.warning(f"[batch_generator] failed to fetch info for table {t}: {e}")
                parts.append(f"## 表：{t}\n获取信息失败: {e}")

        return "\n\n---\n\n".join(parts)

    # ======== Prompt Building ========

    def _build_base_prompt(
        self,
        theme: str,
        tables_info: str,
        schema_supplement: str,
        example_sql: str,
    ) -> str:
        parts = [
            f"## 训练主题（只生成与此主题直接相关的问题）\n{theme}",
            "请确保所有生成的问题都严格围绕这个主题，不要生成与主题无关的问题。",
            "",
            f"## 数据库表结构\n{tables_info}",
        ]

        if schema_supplement.strip():
            parts.extend(["", "## 表结构补充说明", schema_supplement.strip()])

        if example_sql.strip():
            parts.extend(["", "## 示例SQL（表关联参考）", "```sql", example_sql.strip(), "```"])

        return "\n".join(parts)

    # ======== LLM Generation ========

    async def _generate_batch(self, user_prompt: str, batch_size: int) -> List[dict]:
        """调用LLM生成一批问答对"""
        try:
            raw = llm.chat_once_with_retry(
                user_prompt=user_prompt,
                system_prompt=BATCH_SYSTEM_PROMPT,
                temperature=0.8,
                max_tokens=8192,
            )
            return self._parse_response(raw)
        except Exception as e:
            logger.error(f"[batch_generator] LLM call failed: {e}")
            return []

    def _parse_response(self, raw: str) -> List[dict]:
        """从LLM响应中解析JSON数组，支持截断恢复"""
        if not raw:
            return []
        cleaned = raw.strip()

        # 去除 markdown 代码块包裹
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)

        # 尝试直接解析
        try:
            result = json.loads(cleaned)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 数组
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # 尝试修复截断的 JSON：回退到最后一个完整的对象，关闭数组
        entries = self._parse_truncated(cleaned)
        if entries:
            logger.info(f"[batch_generator] salvaged {len(entries)} entries from truncated response")
            return entries

        logger.warning(f"[batch_generator] failed to parse LLM response, raw preview: {raw[:300]}")
        return []

    def _parse_truncated(self, text: str) -> List[dict]:
        """尝试从截断的 JSON 数组中恢复已完成的条目"""
        # 找到数组起始位置
        start = text.find("[")
        if start == -1:
            return []

        inner = text[start + 1:]  # 去掉开头的 [

        # 从后往前找最后一个完整的 } 对象结束位置
        # 策略：找到最后一个 "sql": "..." 后跟着 } 的位置
        objects = []
        depth = 0
        obj_start = -1
        in_string = False
        escape_next = False

        for i, ch in enumerate(inner):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                if depth == 0:
                    obj_start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and obj_start >= 0:
                    obj_text = inner[obj_start:i + 1]
                    try:
                        obj = json.loads(obj_text)
                        if isinstance(obj, dict):
                            objects.append(obj)
                    except json.JSONDecodeError:
                        pass
                    obj_start = -1

        return objects

    # ======== Deduplication ========

    async def _get_existing_questions(self, theme: str) -> set:
        """获取已有问题集合（主记忆库 + 同主题草稿）"""
        questions = set()

        # 从主记忆库获取
        try:
            from backend.services.agentic_qa.vanna.agent import get_vanna_manager, _make_context

            manager = get_vanna_manager()
            ctx = _make_context(manager._memory, "admin")
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    memories = ex.submit(
                        asyncio.run,
                        manager._memory.get_recent_memories(ctx, limit=5000),
                    ).result(timeout=30)
            except RuntimeError:
                memories = asyncio.run(manager._memory.get_recent_memories(ctx, limit=5000))

            for mem in memories:
                q = (mem.question or "").strip() if hasattr(mem, 'question') else ""
                if q:
                    questions.add(q)
        except Exception as e:
            logger.warning(f"[batch_generator] failed to get existing memories: {e}")

        # 从同主题草稿获取
        try:
            collection = self._get_drafts_collection()
            results = collection.get(where={"$and": [{"theme": theme}, {"status": "pending"}]})
            if results and results.get("metadatas"):
                for meta in results["metadatas"]:
                    q = (meta.get("question") or "").strip()
                    if q:
                        questions.add(q)
        except Exception as e:
            logger.warning(f"[batch_generator] failed to get existing drafts: {e}")

        return questions

    def _is_duplicate(self, question: str, existing_questions: set, current_batch: list) -> bool:
        """检查问题是否与已有问题重复"""
        q = question.strip()
        if q in existing_questions:
            return True

        # 模糊匹配
        all_questions = list(existing_questions) + [e["question"] for e in current_batch]
        for eq in all_questions:
            eq = eq.strip()
            if len(q) < 10 or len(eq) < 10:
                continue
            ratio = difflib.SequenceMatcher(None, q, eq).ratio()
            if ratio > 0.85:
                return True

        return False

    # ======== Draft CRUD ========

    def _save_draft(
        self,
        theme: str,
        batch_id: str,
        question: str,
        sql: str,
        tables: List[str],
        alt_questions: Optional[List[str]] = None,
    ) -> Optional[str]:
        """保存草稿到 batch_generated_drafts 集合"""
        try:
            collection = self._get_drafts_collection()
            draft_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            alts = alt_questions or []
            collection.add(
                documents=[question],
                metadatas=[{
                    "draft_id": draft_id,
                    "theme": theme,
                    "batch_id": batch_id,
                    "question": question,
                    "sql": sql,
                    "alt_questions": json.dumps(alts, ensure_ascii=False),
                    "status": "pending",
                    "tables": json.dumps(tables, ensure_ascii=False),
                    "created_at": now,
                }],
                ids=[draft_id],
            )
            return draft_id
        except Exception as e:
            logger.error(f"[batch_generator] save_draft failed: {e}")
            return None

    def list_themes(self) -> List[dict]:
        """列出所有有待审核草稿的主题"""
        try:
            collection = self._get_drafts_collection()
            results = collection.get(where={"status": "pending"})
            if not results or not results.get("metadatas"):
                return []

            theme_map: Dict[str, dict] = {}
            for meta in results["metadatas"]:
                theme = meta.get("theme", "")
                if not theme:
                    continue
                if theme not in theme_map:
                    theme_map[theme] = {"theme": theme, "pending_count": 0, "last_updated": ""}
                theme_map[theme]["pending_count"] += 1
                created = meta.get("created_at", "")
                if created > theme_map[theme]["last_updated"]:
                    theme_map[theme]["last_updated"] = created

            themes = sorted(theme_map.values(), key=lambda x: x["last_updated"], reverse=True)
            return themes
        except Exception as e:
            logger.error(f"[batch_generator] list_themes failed: {e}")
            return []

    def list_drafts(self, theme: str, status: str = "pending", page: int = 1, page_size: int = 20) -> dict:
        """按主题分页查询草稿"""
        try:
            collection = self._get_drafts_collection()
            results = collection.get(where={"$and": [{"theme": theme}, {"status": status}]})

            if not results or not results.get("ids"):
                return {"total": 0, "page": page, "page_size": page_size, "drafts": []}

            ids = results["ids"]
            documents = results["documents"] or [""] * len(ids)
            metadatas = results["metadatas"] or [{}] * len(ids)

            # 按 created_at 倒序
            combined = list(zip(ids, metadatas))
            combined.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)

            total = len(combined)
            start = (page - 1) * page_size
            end = start + page_size
            page_items = combined[start:end]

            drafts = []
            for draft_id, meta in page_items:
                alts_raw = meta.get("alt_questions", "[]")
                try:
                    alt_questions = json.loads(alts_raw) if isinstance(alts_raw, str) else (alts_raw or [])
                except (json.JSONDecodeError, TypeError):
                    alt_questions = []
                drafts.append({
                    "draft_id": draft_id,
                    "theme": meta.get("theme", ""),
                    "question": meta.get("question", ""),
                    "alt_questions": alt_questions,
                    "sql": meta.get("sql", ""),
                    "status": meta.get("status", "pending"),
                    "created_at": meta.get("created_at", ""),
                })

            return {"total": total, "page": page, "page_size": page_size, "drafts": drafts}
        except Exception as e:
            logger.error(f"[batch_generator] list_drafts failed: {e}")
            return {"total": 0, "page": page, "page_size": page_size, "drafts": []}

    def get_draft(self, draft_id: str) -> Optional[dict]:
        """获取单条草稿"""
        try:
            collection = self._get_drafts_collection()
            result = collection.get(ids=[draft_id])
            if result and result.get("ids"):
                meta = (result.get("metadatas") or [{}])[0]
                alts_raw = meta.get("alt_questions", "[]")
                try:
                    alt_questions = json.loads(alts_raw) if isinstance(alts_raw, str) else (alts_raw or [])
                except (json.JSONDecodeError, TypeError):
                    alt_questions = []
                return {
                    "draft_id": draft_id,
                    "theme": meta.get("theme", ""),
                    "question": meta.get("question", ""),
                    "alt_questions": alt_questions,
                    "sql": meta.get("sql", ""),
                    "status": meta.get("status", "pending"),
                    "created_at": meta.get("created_at", ""),
                }
        except Exception as e:
            logger.error(f"[batch_generator] get_draft failed: {e}")
        return None

    def approve_drafts(self, draft_ids: List[str]) -> dict:
        """批量通过草稿 → 写入主记忆库 + 更新草稿状态"""
        from backend.services.agentic_qa.vanna.agent import get_vanna_manager, _make_context

        manager = get_vanna_manager()
        ctx = _make_context(manager._memory, "admin")
        approved = 0
        failed = 0

        for draft_id in draft_ids:
            try:
                draft = self.get_draft(draft_id)
                if not draft:
                    failed += 1
                    continue

                question = draft.get("question", "")
                sql_text = draft.get("sql", "")
                alt_questions = draft.get("alt_questions", [])
                theme = draft.get("theme", "")

                # 构建要写入的问答对列表（主问题 + 备选问题，都指向同一个SQL）
                qa_pairs = [{"question": question, "sql": sql_text}]
                for alt_q in alt_questions:
                    alt_q = alt_q.strip()
                    if alt_q and alt_q != question:
                        qa_pairs.append({"question": alt_q, "sql": sql_text})

                # 逐条写入主记忆库
                save_meta = {"theme": theme} if theme else None
                for qa in qa_pairs:
                    try:
                        loop = asyncio.get_running_loop()
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                            ex.submit(
                                asyncio.run,
                                manager._memory.save_tool_usage(
                                    question=qa["question"],
                                    tool_name="run_sql",
                                    args={"sql": qa["sql"]},
                                    context=ctx,
                                    success=True,
                                    metadata=save_meta,
                                ),
                            ).result(timeout=15)
                    except RuntimeError:
                        asyncio.run(manager._memory.save_tool_usage(
                            question=qa["question"],
                            tool_name="run_sql",
                            args={"sql": qa["sql"]},
                            context=ctx,
                            success=True,
                            metadata=save_meta,
                        ))

                # 更新草稿状态
                self._update_draft_status(draft_id, "approved")
                approved += 1
                logger.info(f"[batch_generator] approved draft {draft_id}: {question[:50]}")

            except Exception as e:
                logger.error(f"[batch_generator] approve draft {draft_id} failed: {e}")
                failed += 1

        return {"approved": approved, "failed": failed}

    def update_draft(self, draft_id: str, question: str, sql_text: str, alt_questions: Optional[List[str]] = None, theme: Optional[str] = None) -> bool:
        """编辑单条草稿"""
        try:
            collection = self._get_drafts_collection()
            result = collection.get(ids=[draft_id])
            if not result or not result.get("ids"):
                return False

            meta = (result.get("metadatas") or [{}])[0]
            meta["question"] = question
            meta["sql"] = sql_text
            if alt_questions is not None:
                meta["alt_questions"] = json.dumps(alt_questions, ensure_ascii=False)
            if theme is not None:
                meta["theme"] = theme

            collection.update(
                ids=[draft_id],
                documents=[question],
                metadatas=[meta],
            )
            return True
        except Exception as e:
            logger.error(f"[batch_generator] update_draft failed: {e}")
            return False

    def delete_drafts(self, draft_ids: List[str]) -> dict:
        """批量软删除草稿"""
        deleted = 0
        failed = 0
        for draft_id in draft_ids:
            if self._update_draft_status(draft_id, "deleted"):
                deleted += 1
            else:
                failed += 1
        return {"deleted": deleted, "failed": failed}

    def _update_draft_status(self, draft_id: str, status: str) -> bool:
        """更新草稿状态（软删除/标记通过）"""
        try:
            collection = self._get_drafts_collection()
            result = collection.get(ids=[draft_id])
            if not result or not result.get("ids"):
                return False

            meta = (result.get("metadatas") or [{}])[0]
            doc = (result.get("documents") or [""])[0]
            meta["status"] = status

            collection.update(ids=[draft_id], documents=[doc], metadatas=[meta])
            return True
        except Exception as e:
            logger.error(f"[batch_generator] update_draft_status failed: {e}")
            return False


# 模块级单例
_batch_generator: Optional[BatchGenerator] = None


def get_batch_generator() -> BatchGenerator:
    global _batch_generator
    if _batch_generator is None:
        _batch_generator = BatchGenerator()
    return _batch_generator
