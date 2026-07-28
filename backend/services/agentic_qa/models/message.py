"""消息模型"""
from typing import Optional
from sqlalchemy import String, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.core.agentic_qa.database import Base


class ChatMessage(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sql: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    results: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # JSON
    steps: Mapped[Optional[str]] = mapped_column(Text, nullable=True)         # JSON
    intent: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    analysis_chart: Mapped[Optional[str]] = mapped_column(Text, nullable=True)     # JSON
    analysis_suggestions: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # JSON
    result_groups: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # JSON
    feedback_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    feedback_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entity_candidates: Mapped[Optional[str]] = mapped_column(Text, nullable=True)    # JSON
    needs_clarification: Mapped[Optional[bool]] = mapped_column(default=False)
    clarification_options: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # JSON
    clarification_groups: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    followups: Mapped[Optional[str]] = mapped_column(Text, nullable=True)             # JSON
    thinking: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rag_thinking: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rag_references: Mapped[Optional[str]] = mapped_column(Text, nullable=True)      # JSON
    timestamp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    session = relationship("ChatSession", back_populates="messages")

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "sql": self.sql,
            "results": _json_loads(self.results),
            "steps": _json_loads(self.steps),
            "intent": self.intent,
            "source": self.source,
            "analysis_chart": _json_loads(self.analysis_chart),
            "analysis_suggestions": _json_loads(self.analysis_suggestions),
            "result_groups": _json_loads(self.result_groups),
            "feedback_status": self.feedback_status,
            "feedback_text": self.feedback_text,
            "entity_candidates": _json_loads(self.entity_candidates),
            "needs_clarification": self.needs_clarification,
            "clarification_options": _json_loads(self.clarification_options),
            "clarification_groups": _json_loads(self.clarification_groups),
            "followups": _json_loads(self.followups),
            "thinking": self.thinking,
            "rag_thinking": self.rag_thinking,
            "rag_references": _json_loads(self.rag_references),
            "timestamp": self.timestamp,
        }


def _json_loads(val):
    if val is None:
        return None
    import json
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return val
