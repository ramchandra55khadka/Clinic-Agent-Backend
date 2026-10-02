"""Refresh-token repositories (rotation and revocation)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.user_account import RefreshToken


def create_refresh_token(
    db: Session,
    *,
    user_id: str,
    token_hash: str,
    expires_at: datetime,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=user_agent,
        client_ip=client_ip,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def rotate_refresh_token(
    db: Session,
    token: RefreshToken,
    *,
    user_id: str,
    token_hash: str,
    expires_at: datetime,
    user_agent: str | None = None,
    client_ip: str | None = None,
) -> RefreshToken:
    """Issues the replacement token and marks the presented one as rotated."""
    replacement = create_refresh_token(
        db,
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=user_agent,
        client_ip=client_ip,
    )
    token.revoked_at = datetime.now(UTC)
    token.replaced_by_id = replacement.id
    db.commit()
    return replacement


def get_refresh_token(db: Session, token_hash: str):
    return db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()


def revoke_refresh_token(db: Session, token: RefreshToken, replaced_by_id: int | None = None) -> None:
    token.revoked_at = datetime.now(UTC)
    token.replaced_by_id = replaced_by_id
    db.commit()


def revoke_user_refresh_tokens(db: Session, user_id: str) -> int:
    """Revokes every active refresh token of a user (used on password change)."""
    now = datetime.now(UTC)
    tokens = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .all()
    )
    for token in tokens:
        token.revoked_at = now
    db.commit()
    return len(tokens)
