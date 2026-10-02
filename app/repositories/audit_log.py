"""Audit-trail repository."""

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user_account import UserAccount


def log_audit(
    db: Session,
    *,
    action: str,
    actor: UserAccount | None = None,
    actor_email: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    detail: str | None = None,
) -> None:
    """Records a security-relevant event. Never raises into the request path."""
    try:
        db.add(
            AuditLog(
                actor_id=actor.id if actor else None,
                actor_email=actor_email or (actor.email if actor else None),
                action=action,
                entity=entity,
                entity_id=None if entity_id is None else str(entity_id),
                client_ip=client_ip,
                user_agent=user_agent,
                detail=detail,
            )
        )
        db.commit()
    except Exception:  # pragma: no cover - auditing must not break requests
        db.rollback()
