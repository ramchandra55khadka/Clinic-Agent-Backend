"""Slot-based durable patient preferences extracted from chat."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint, func

from app.db.base import Base


class LongTermMemory(Base):
    __tablename__ = "long_term_memory"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_memory_user_key"),
    )

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid4()))
    user_id = Column(String(36), ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(50), nullable=False)
    value = Column(String(200), nullable=False)
    source_conversation_id = Column(String(36), ForeignKey("conversation.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    @property
    def content(self) -> str:
        """Backward-compatible display text for existing clients."""
        return f"{self.key.replace('_', ' ').title()}: {self.value}"

    @property
    def kind(self) -> str:
        return "preference"

    @property
    def source(self) -> str:
        return "chat"

    @property
    def confidence(self) -> float:
        return 1.0

    @property
    def last_seen_at(self):
        return self.last_used_at or self.updated_at
