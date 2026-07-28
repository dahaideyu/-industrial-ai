# cython: annotation_typing=False, infer_types=False, language_level=3
"""Vanna 2.0 Agent — NL2SQL 通用数据库查询引擎

使用 Vanna Agent + ChromaAgentMemory + LifecycleHook 构建。
Agent 负责理解问题、生成 SQL、调用工具执行查询。
训练通过前端 API 驱动，不再硬编码初始化数据。
"""
import os
import uuid
import asyncio
from typing import Optional, List, Dict, Any, AsyncGenerator
from vanna import Agent, ToolRegistry
from vanna.tools import RunSqlTool
from vanna.core import (
    AgentConfig,
    DefaultSystemPromptBuilder,
    LifecycleHook,
    ToolContext,
)
from vanna.core.user.models import User
from vanna.core.user.resolver import UserResolver
from vanna.core.user.request_context import RequestContext
from vanna.integrations.chromadb import ChromaAgentMemory
from vanna.integrations.mysql import MySQLRunner as VannaMySQLRunner
from backend.services.agentic_qa.vanna.deepseek_llm import LlmServiceImpl
from backend.services.agentic_qa.vanna.guard import SqlSecurityHook
from backend.core.agentic_qa.config import settings
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("vanna.agent")

GENERIC_SQL_SYSTEM_PROMPT = """你是一个专业的数据库查询助手，运行在 MySQL 数据库上。

## 职责
1. 理解用户的自然语言问题，生成正确的 SQL 查询
2. 查询前先通过 INFORMATION_SCHEMA 了解表结构
3. 生成高效、安全的 SELECT 查询

## 核心规则
1. 只生成 SELECT 语句，绝对禁止 INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE
2. 始终使用 LIMIT 限制结果数量（最多 1000 条）
3. 不确定表名或字段名时，先用 SHOW TABLES 或 DESCRIBE 确认
4. 关联查询时确保 JOIN 条件正确
5. 对于统计类问题，同时返回汇总数量和明细列表
6. 参考记忆库中相似的历史问答来提升准确性
"""


class AdminUserResolver(UserResolver):
    def resolve_user(self, request_context: RequestContext) -> User:
        return User(
            id=request_context.user_id,
            username=request_context.user_id,
            group_memberships=["admin", "user"]
        )


def _make_context(agent_memory, user_id: str = "admin") -> ToolContext:
    return ToolContext(
        user=User(id=user_id, username=user_id, group_memberships=["admin", "user"]),
        conversation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        agent_memory=agent_memory,
        metadata={},
        observability_provider=None
    )


class VannaAgentManager:
    """Vanna Agent 管理器 — 封装初始化、训练、查询"""

    def __init__(self):
        self._agent: Optional[Agent] = None
        self._memory: Optional[ChromaAgentMemory] = None
        self._llm_service: Optional[LlmServiceImpl] = None
        self._runner: Optional[VannaMySQLRunner] = None

    def reset(self):
        """重置 Agent，释放旧 ChromaDB 连接（清空向量库后调用）"""
        self._agent = None
        self._memory = None
        self._llm_service = None
        logger.info("[vanna] agent reset — will reinitialize on next use")

    @property
    def memory(self) -> ChromaAgentMemory:
        if self._memory is None:
            self.init()
        return self._memory

    def init(self) -> "VannaAgentManager":
        """同步初始化 Agent + ChromaAgentMemory"""
        if self._agent is not None:
            return self

        persist_dir = settings.vanna_chroma_path or "./backend/data/agentic_qa/vanna-knowledge"
        logger.info(f"[vanna] initializing with ChromaDB at {persist_dir}")

        from backend.core.agentic_qa.embeddings import get_embedding_function
        self._memory = ChromaAgentMemory(
            persist_directory=persist_dir,
            collection_name="industrial_sql_memories",
            embedding_function=get_embedding_function()
        )

        self._llm_service = LlmServiceImpl()
        logger.info(f"[vanna] LLM service: provider={os.getenv('PROVIDER', 'deepseek')}, model={settings.deepseek_model}")

        self._runner = VannaMySQLRunner(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database
        )
        logger.info(f"[vanna] MySQL runner: {settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}")

        tool_registry = ToolRegistry()
        tool_registry.register_local_tool(
            RunSqlTool(
                sql_runner=self._runner,
                custom_tool_name="run_sql",
                custom_tool_description="执行 MySQL 查询语句并返回结果"
            ),
            access_groups=["admin", "user"]
        )

        config = AgentConfig(
            max_tool_iterations=3,
            temperature=0.1,
            stream_responses=False,
            auto_save_conversations=True
        )

        self._agent = Agent(
            llm_service=self._llm_service,
            tool_registry=tool_registry,
            user_resolver=AdminUserResolver(),
            agent_memory=self._memory,
            config=config,
            system_prompt_builder=DefaultSystemPromptBuilder(
                base_prompt=GENERIC_SQL_SYSTEM_PROMPT
            ),
            lifecycle_hooks=[SqlSecurityHook()]
        )

        logger.info("[vanna] Agent initialization complete")
        return self

    # ---- 记忆检索（供 LangGraph 使用） ----

    def search_similar_questions(self, question: str, limit: int = 5) -> list:
        """搜索相似的历史问题及其 SQL"""
        ctx = _make_context(self._memory, "admin")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self._memory.search_similar_usage(question, ctx, limit=limit)
            )
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                asyncio.run,
                self._memory.search_similar_usage(question, ctx, limit=limit)
            )
            return future.result(timeout=30)

    def search_docs(self, query: str, limit: int = 5) -> list:
        """搜索相关文档：Vanna 文本记忆（含表结构 + 训练文档）"""
        return self.search_table_schemas(query, limit=limit)

    # 已索引的表名集合（存储在 ChromaDB metadata 中用于追踪）
    def _get_indexed_table_set(self) -> set:
        """从文本记忆中提取已索引的表名"""
        ctx = _make_context(self._memory, "admin")
        recent = self._run_async_safe(
            self._memory.get_recent_text_memories(ctx, limit=500)
        )

        indexed = set()
        for m in recent:
            content = m.content if hasattr(m, 'content') else str(m)
            # 文档格式: "表: table_name (...)" 或 "TABLE_SCHEMA:table_name|..."
            if content.startswith("TABLE_SCHEMA:"):
                tn = content.split("|")[0].replace("TABLE_SCHEMA:", "").strip()
                if tn:
                    indexed.add(tn)
            elif content.startswith("表: "):
                tn = content.split("\n")[0].replace("表: ", "").split(" (")[0].strip()
                if tn:
                    indexed.add(tn)
        return indexed

    # ======== 表结构索引（使用独立 ChromaDB 集合，避免事件循环冲突） ========

    def _get_review_collection(self):
        """获取训练审核队列集合"""
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from backend.core.agentic_qa.embeddings import get_embedding_function
        path = settings.vanna_chroma_path or "./backend/data/agentic_qa/vanna-knowledge"
        client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True)
        )
        try:
            return client.get_collection(name="training_review_queue")
        except Exception:
            return client.get_or_create_collection(name="training_review_queue", embedding_function=get_embedding_function())

    def _get_schema_collection(self):
        """获取表结构索引专用集合（复用 Vanna memory 的 ChromaDB 连接）"""
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from backend.core.agentic_qa.embeddings import get_embedding_function
        path = settings.vanna_chroma_path or "./backend/data/agentic_qa/vanna-knowledge"
        # 必须与 Vanna ChromaAgentMemory 的 settings 一致，否则会冲突
        client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True)
        )
        try:
            return client.get_collection(name="table_schema_index")
        except Exception:
            return client.get_or_create_collection(name="table_schema_index", embedding_function=get_embedding_function())

    def get_batch_drafts_collection(self):
        """获取批量生成草稿集合（与 Vanna memory 共享 ChromaDB 客户端配置）"""
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from backend.core.agentic_qa.embeddings import get_embedding_function
        path = settings.vanna_chroma_path or "./backend/data/agentic_qa/vanna-knowledge"
        client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True)
        )
        try:
            return client.get_collection(name="batch_generated_drafts")
        except Exception:
            return client.get_or_create_collection(
                name="batch_generated_drafts",
                embedding_function=get_embedding_function(),
            )

    def index_table_schemas(self, table_names: list = None) -> dict:
        """选择性索引表结构（同步操作，直接使用 ChromaDB）"""
        from backend.services.agentic_qa.db.mysql import get_all_tables, db

        collection = self._get_schema_collection()
        all_tables = get_all_tables()
        if table_names is None:
            table_names = all_tables[:100]

        # 获取已索引的表
        try:
            existing = collection.get()
            indexed_ids = set(existing["ids"]) if existing and existing["ids"] else set()
        except Exception:
            indexed_ids = set()

        result = {"indexed": [], "errors": []}

        for table_name in table_names:
            if table_name not in all_tables:
                result["errors"].append(f"{table_name}: 表不存在")
                continue

            try:
                rows = db.execute_query(f"SHOW CREATE TABLE `{table_name}`")
                ddl = rows[0].get("Create Table", "") if rows else ""

                try:
                    comment_rows = db.execute_query(
                        "SELECT TABLE_COMMENT FROM INFORMATION_SCHEMA.TABLES "
                        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                        (settings.mysql_database, table_name)
                    )
                    table_comment = comment_rows[0].get("TABLE_COMMENT", "") if comment_rows else ""
                except Exception:
                    table_comment = ""

                cols = db.execute_query(f"DESCRIBE `{table_name}`")
                col_lines = []
                for c in cols:
                    comment_str = f" -- {c['Comment']}" if c.get('Comment') else ""
                    col_lines.append(f"  {c['Field']} {c['Type']}{comment_str}")

                doc = f"表: {table_name}"
                if table_comment:
                    doc += f" ({table_comment})"
                doc += "\n字段:\n" + "\n".join(col_lines)
                if ddl:
                    doc += f"\n建表语句:\n{ddl[:2000]}"

                doc_id = f"schema:{table_name}"

                # Upsert: delete old then add
                if doc_id in indexed_ids:
                    collection.delete(ids=[doc_id])
                    indexed_ids.discard(doc_id)

                collection.add(
                    ids=[doc_id],
                    documents=[doc],
                    metadatas=[{
                        "table_name": table_name,
                        "table_comment": table_comment,
                        "type": "table_schema",
                    }]
                )
                indexed_ids.add(doc_id)
                result["indexed"].append(table_name)
                logger.info(f"[vanna] indexed schema: {table_name}")

            except Exception as e:
                result["errors"].append(f"{table_name}: {str(e)}")
                logger.error(f"[vanna] index schema error {table_name}: {e}")

        logger.info(f"[vanna] schema indexing: {len(result['indexed'])} indexed, {len(result['errors'])} errors")
        return result

    def unindex_tables(self, table_names: list) -> dict:
        """从索引中删除指定表"""
        collection = self._get_schema_collection()
        result = {"removed": [], "not_found": []}

        for table_name in table_names:
            doc_id = f"schema:{table_name}"
            try:
                existing = collection.get(ids=[doc_id])
                if existing and existing["ids"]:
                    collection.delete(ids=[doc_id])
                    result["removed"].append(table_name)
                else:
                    result["not_found"].append(table_name)
            except Exception as e:
                result["not_found"].append(table_name)

        logger.info(f"[vanna] unindexed: {result['removed']}")
        return result

    def get_index_status(self) -> dict:
        """获取所有表的索引状态"""
        from backend.services.agentic_qa.db.mysql import get_all_tables
        all_tables = get_all_tables()
        collection = self._get_schema_collection()
        try:
            existing = collection.get()
            indexed = [m["table_name"] for m in (existing["metadatas"] or [])] if existing and existing.get("metadatas") else []
        except Exception:
            indexed = []
        return {
            "all_tables": all_tables,
            "indexed_tables": indexed,
            "total": len(all_tables),
            "indexed_count": len(indexed),
        }

    def search_table_schemas(self, query: str, limit: int = 8) -> list:
        """搜索相关表结构（供 SQL 生成使用）"""
        collection = self._get_schema_collection()
        try:
            results = collection.query(query_texts=[query], n_results=limit)
        except Exception:
            return []

        if not results or not results.get("documents") or not results["documents"][0]:
            return []

        docs = []
        for i, doc in enumerate(results["documents"][0]):
            meta = (results["metadatas"][0] or [{}])[i] if results.get("metadatas") else {}
            docs.append(type('Doc', (), {
                'content': doc,
                'metadata': meta
            })())
        return docs

    def save_successful_query(self, question: str, sql: str):
        """保存成功的查询到记忆库"""
        logger.debug(f"[vanna] saving successful query: '{question[:60]}'")
        ctx = _make_context(self._memory, "admin")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._memory.save_tool_usage(
                question=question, tool_name="run_sql",
                args={"sql": sql}, context=ctx, success=True
            ))
            return
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                asyncio.run,
                self._memory.save_tool_usage(
                    question=question, tool_name="run_sql",
                    args={"sql": sql}, context=ctx, success=True
                )
            )
            future.result(timeout=10)

    # ---- Vanna Agent 黑盒查询 ----

    async def ask_async(self, question: str, user_id: str = "admin") -> str:
        """异步调用 Vanna Agent 的 send_message"""
        if self._agent is None:
            self.init()

        request_ctx = RequestContext(
            user_id=user_id,
            conversation_id=str(uuid.uuid4())
        )

        full_response = []
        async for component in self._agent.send_message(request_ctx, question):
            text = getattr(component, 'text', None)
            if text:
                full_response.append(text)

        return "\n".join(full_response)

    def ask_sync(self, question: str, user_id: str = "admin") -> str:
        """同步查询 Vanna Agent"""
        return asyncio.run(self.ask_async(question, user_id))


# 全局单例
_manager: Optional[VannaAgentManager] = None


def get_vanna_manager() -> VannaAgentManager:
    global _manager
    if _manager is None:
        _manager = VannaAgentManager()
        _manager.init()
    return _manager


def init_vanna_agent():
    """FastAPI 启动时初始化"""
    return get_vanna_manager()
