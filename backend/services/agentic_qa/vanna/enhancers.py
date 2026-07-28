# cython: annotation_typing=False, infer_types=False, language_level=3
"""Vanna LLM Context Enhancers — 注入表结构 + 检索记忆库"""
import asyncio
from typing import List
from vanna.core.enhancer import LlmContextEnhancer
from vanna.core.llm import LlmMessage
from vanna.core.user.models import User
from vanna.integrations.chromadb import ChromaAgentMemory
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("vanna.enhancers")


class SchemaContextEnhancer(LlmContextEnhancer):
    """将数据库表结构注入到 LLM 系统提示词中

    从 ChromaAgentMemory 的文本记忆中检索相关的表结构信息，
    确保 LLM 能了解数据库中存在的表和字段。
    """

    def __init__(self, agent_memory: ChromaAgentMemory):
        self._memory = agent_memory

    async def enhance_system_prompt(
        self, system_prompt: str, user_message: str, user: User
    ) -> str:
        """检索相关表结构并追加到 system prompt"""
        try:
            from backend.services.agentic_qa.vanna.agent import _make_context
            ctx = _make_context(self._memory, user.id if user else "admin")
            memories = await self._memory.get_recent_text_memories(ctx, limit=200)
        except Exception as e:
            logger.debug(f"[enhancer] schema fetch failed: {e}")
            return system_prompt

        if not memories:
            return system_prompt

        # 关键词过滤（支持中文：用2-3字滑动窗口提取关键词）
        query_lower = user_message.lower()
        keywords = set()
        for kw in query_lower.split():
            if len(kw) >= 2:
                keywords.add(kw)
        # 中文滑动窗口：提取2字和3字片段
        for n in (2, 3):
            for i in range(len(user_message) - n + 1):
                chunk = user_message[i:i+n]
                if not all('一' <= c <= '鿿' or c.isalpha() for c in chunk):
                    continue
                keywords.add(chunk)

        schema_parts = []
        seen = set()
        for m in memories:
            content = m.content if hasattr(m, 'content') else str(m)
            content_key = content[:80]
            if content_key in seen:
                continue
            is_schema = content.startswith("TABLE_SCHEMA:") or "表:" in content[:10]
            content_lower = content.lower()
            if is_schema and any(kw.lower() in content_lower for kw in keywords):
                schema_parts.append(content[:1500])
                seen.add(content_key)

        if schema_parts:
            schema_block = "\n\n---\n".join(schema_parts[:5])
            enhanced = f"{system_prompt}\n\n## 相关数据库表结构\n{schema_block}"
            logger.info(f"[enhancer] injected {len(schema_parts)} table schemas for query")
            return enhanced

        return system_prompt

    async def enhance_user_messages(
        self, messages: List[LlmMessage], user: User
    ) -> List[LlmMessage]:
        return messages


class MemoryRetrievalEnhancer(LlmContextEnhancer):
    """从 Vanna 记忆库检索相似历史问答，注入到系统提示词"""

    def __init__(self, agent_memory: ChromaAgentMemory):
        self._memory = agent_memory

    async def enhance_system_prompt(
        self, system_prompt: str, user_message: str, user: User
    ) -> str:
        """检索相似历史问答（从 tool usage 记忆中）"""
        try:
            from backend.services.agentic_qa.vanna.agent import _make_context
            ctx = _make_context(self._memory, user.id if user else "admin")
            # 使用 get_recent_memories 替代 broken 的 search_similar_usage
            all_memories = await self._memory.get_recent_memories(ctx, limit=100)
        except Exception as e:
            logger.debug(f"[enhancer] memory fetch failed: {e}")
            return system_prompt

        if not all_memories:
            return system_prompt

        # 关键词评分（支持中文滑动窗口）
        keywords = set()
        for kw in user_message.lower().split():
            if len(kw) >= 2:
                keywords.add(kw)
        for n in (2, 3):
            for i in range(len(user_message) - n + 1):
                chunk = user_message[i:i+n]
                if all('一' <= c <= '鿿' or c.isalpha() for c in chunk):
                    keywords.add(chunk)
        scored = []
        for mem in all_memories:
            q = (mem.question if hasattr(mem, 'question') else '').lower()
            args = mem.args if hasattr(mem, 'args') else {}
            sql = (args.get("sql", "") if isinstance(args, dict) else "").lower()
            score = sum(1 for kw in keywords if kw in q or kw in sql)
            if score > 0 and sql:
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)

        examples = []
        for _, mem in scored[:5]:
            q = mem.question if hasattr(mem, 'question') else str(mem)
            args = mem.args if hasattr(mem, 'args') else {}
            sql = args.get("sql", "") if isinstance(args, dict) else ""
            if sql and '[待审核]' not in q:
                examples.append(f"问题: {q}\n参考SQL: {sql}")

        if examples:
            example_block = "\n\n---\n".join(examples)
            enhanced = f"{system_prompt}\n\n## 相似历史问答（严格参考其SQL结构）\n{example_block}"
            logger.info(f"[enhancer] injected {len(examples)} similar examples")
            return enhanced

        return system_prompt

    async def enhance_user_messages(
        self, messages: List[LlmMessage], user: User
    ) -> List[LlmMessage]:
        return messages


class CombinedEnhancer(LlmContextEnhancer):
    """组合多个 Enhancer"""

    def __init__(self, enhancers: List[LlmContextEnhancer]):
        self._enhancers = enhancers

    async def enhance_system_prompt(
        self, system_prompt: str, user_message: str, user: User
    ) -> str:
        for enhancer in self._enhancers:
            try:
                system_prompt = await enhancer.enhance_system_prompt(
                    system_prompt, user_message, user
                )
            except Exception as e:
                logger.warning(f"[enhancer] {enhancer.__class__.__name__} failed: {e}")
        return system_prompt

    async def enhance_user_messages(
        self, messages: List[LlmMessage], user: User
    ) -> List[LlmMessage]:
        for enhancer in self._enhancers:
            try:
                messages = await enhancer.enhance_user_messages(messages, user)
            except Exception:
                pass
        return messages
