# cython: annotation_typing=False, infer_types=False, language_level=3
"""Memory Hub — unified read/write interface over existing storage backends."""
import time
import uuid
from typing import Any, Dict, List, Optional
from backend.core.agentic_qa.logger import get_logger

logger = get_logger("agentic_qa.memory")


class MemoryHub:
    """Unified memory facade. All 3 Agents read/write through this single interface."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._session_cache: Dict[str, Any] = {}

    # ── Session Memory (in-process dict, session lifetime) ──

    def get_session_context(self) -> Dict[str, Any]:
        """Return cached entity_context + last_query + intermediate state."""
        return {
            "entity_context": self._session_cache.get("entity_context", {}),
            "last_query": self._session_cache.get("last_query"),
            "analysis_suggestions": self._session_cache.get("analysis_suggestions", []),
            "matched_metrics": self._session_cache.get("matched_metrics", []),
        }

    def update_session(self, key: str, value: Any) -> None:
        """Write a key to the session-level cache."""
        self._session_cache[key] = value

    # ── Short-Term Memory (ChatMessage table, MySQL) ──

    def get_conversation_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Read recent N rounds from ChatMessage table for this session."""
        from backend.services.agentic_qa.models.message import ChatMessage
        from backend.core.agentic_qa.database import SessionLocal

        db_session = SessionLocal()
        try:
            messages = (
                db_session.query(ChatMessage)
                .filter(ChatMessage.session_id == self.session_id)
                .order_by(ChatMessage.timestamp.desc())
                .limit(limit)
                .all()
            )
            history = []
            for msg in reversed(messages):
                history.append({
                    "role": msg.role,
                    "content": msg.content,
                    "sql": msg.sql,
                })
            return history
        except Exception as e:
            logger.warning(f"[memory] get_conversation_history failed: {e}")
            return []
        finally:
            db_session.close()

    def append_message(
        self, role: str, content: str,
        sql: Optional[str] = None,
        steps: Optional[List[Dict]] = None,
    ) -> None:
        """Write a message to ChatMessage table."""
        from backend.services.agentic_qa.models.message import ChatMessage
        from backend.core.agentic_qa.database import SessionLocal
        import json

        db_session = SessionLocal()
        try:
            msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=self.session_id,
                role=role,
                content=content,
                sql=sql,
                steps=json.dumps(steps, ensure_ascii=False) if steps else None,
                timestamp=int(time.time() * 1000),
            )
            db_session.add(msg)
            db_session.commit()
        except Exception as e:
            logger.warning(f"[memory] append_message failed: {e}")
            db_session.rollback()
        finally:
            db_session.close()

    # ── Long-Term Memory (Vanna ChromaDB) ──

    def search_similar_queries(self, question: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search Vanna memory for similar historical Q&A pairs (excludes [待审核] prefix)."""
        from backend.services.agentic_qa.vanna.agent import get_vanna_manager

        manager = get_vanna_manager()
        try:
            results = manager.search_similar_questions(question, limit=top_k)
            pairs = []
            for r in (results or []):
                q = r.question if hasattr(r, 'question') else str(r)
                if q.startswith("[待审核]") or q.startswith("[待审核-反馈]"):
                    continue
                args = r.args if hasattr(r, 'args') else {}
                sql = args.get("sql", "") if isinstance(args, dict) else ""
                if sql:
                    pairs.append({"question": q, "sql": sql})
            return pairs[:top_k]
        except Exception as e:
            logger.warning(f"[memory] search_similar_queries failed: {e}")
            return []

    async def save_query_pair(self, question: str, sql: str, status: str = "pending") -> None:
        """Save a Q&A pair to Vanna memory. status='pending' adds [待审核] prefix."""
        from backend.services.agentic_qa.vanna.agent import get_vanna_manager, _make_context

        manager = get_vanna_manager()
        try:
            prefix = "[待审核] " if status == "pending" else ""
            ctx = _make_context(manager._memory)
            await manager._memory.save_tool_usage(
                question=prefix + question,
                tool_name="run_sql",
                args={"sql": sql},
                context=ctx,
                success=True,
            )
            logger.info(f"[memory] saved query pair (status={status}): {question[:60]}...")
        except Exception as e:
            logger.warning(f"[memory] save_query_pair failed: {e}")

    # ── Capability Context (real-time aggregation, not persisted) ──

    def get_capability_context(self, question: str) -> Dict[str, Any]:
        """Aggregate 4 sources: entities, schemas, training topics, history — for Planner."""
        entities = self._query_entity_index(question)
        schemas = self._query_schema_index(question)
        topics = self._query_training_topics()
        history = self.get_conversation_history(limit=5)
        return {
            "available_entities": entities,
            "available_schemas": schemas,
            "training_topics": topics,
            "recent_queries": [
                {"role": h.get("role"), "content": h.get("content", "")[:100]}
                for h in history[-3:]
            ],
        }

    def _query_entity_index(self, question: str, top_k: int = 10) -> List[Dict]:
        """Query entity ChromaDB index for matching entities."""
        try:
            from backend.services.agentic_qa.agents.entity_resolver import search_entity_vector
            results = search_entity_vector(question, limit=top_k)
            return [
                {"name": r.get("label", ""), "type": r.get("entity_type", ""), "label": r.get("label", "")}
                for r in (results or [])
            ]
        except Exception as e:
            logger.warning(f"[memory] _query_entity_index failed: {e}")
            return []

    def _query_schema_index(self, question: str, top_k: int = 5) -> List[str]:
        """Query table schema index for relevant tables."""
        try:
            from backend.services.agentic_qa.vanna.agent import get_vanna_manager
            manager = get_vanna_manager()
            results = manager.search_table_schemas(question, limit=top_k)
            return [r.content if hasattr(r, 'content') else str(r) for r in (results or [])]
        except Exception as e:
            logger.warning(f"[memory] _query_schema_index failed: {e}")
            return []

    def _query_training_topics(self) -> List[str]:
        """Read training topics from custom metrics and Vanna memory."""
        topics = []
        try:
            from backend.services.agentic_qa.agents.entity_resolver import load_custom_metrics
            metrics = load_custom_metrics()
            for m in (metrics or []):
                name = m.get("name") or m.get("metric_name", "")
                desc = m.get("description") or m.get("definition", "")
                if name:
                    topics.append(f"{name}: {desc}" if desc else name)
        except Exception as e:
            logger.warning(f"[memory] _query_training_topics failed: {e}")
        return topics[:20]

    # ── Reserved: Long-Term Experience Memory ──

    def save_experience(self, pattern: str, lesson: str) -> None:
        """Reserved: save experiential lesson to long-term memory. No-op for now."""
        pass

    def search_experience(self, question: str) -> List[Dict[str, Any]]:
        """Reserved: search experiential lessons. Returns empty list for now."""
        return []


# Per-session MemoryHub instances
_memory_hubs: Dict[str, MemoryHub] = {}


def get_memory_hub(session_id: str) -> MemoryHub:
    """Get or create a MemoryHub for a session."""
    if session_id not in _memory_hubs:
        _memory_hubs[session_id] = MemoryHub(session_id)
    return _memory_hubs[session_id]
