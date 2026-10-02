"""Security-relevant events (sign-ins, lockouts, bookings, admin changes)."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, func

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_action_created", "action", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(String(36), ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_email = Column(String, nullable=True)
    action = Column(String(64), nullable=False, index=True)
    entity = Column(String(64), nullable=True)
    entity_id = Column(String, nullable=True)
    client_ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
