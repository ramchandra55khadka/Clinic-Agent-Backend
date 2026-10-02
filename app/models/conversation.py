"""Chat sessions and their individual turns."""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class Conversation(Base):
    __tablename__ = "conversation"
    __table_args__ = (
        UniqueConstraint("user_id", "session_id", name="uq_conversation_user_session"),
    )

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid4()))
    session_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True)
    state_json = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    title = Column(String(200), nullable=True)
    message_count = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    messages = relationship("ConversationMessage", back_populates="conversation", cascade="all, delete-orphan")


class ConversationMessage(Base):
    __tablename__ = "conversation_message"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(36), ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    intent = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    conversation = relationship("Conversation", back_populates="messages")
    __table_args__ = (
        Index("ix_conversation_message_conversation_created_at", "conversation_id", "created_at"),
    )
