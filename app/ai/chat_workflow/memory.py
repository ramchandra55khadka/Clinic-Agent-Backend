import json
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy.orm import Session

from app.models.conversation import Conversation


def get_session(db: Session, session_id: str, user_id: str) -> dict[str, Any]:
    conv = db.query(Conversation).filter(
        Conversation.session_id == session_id,
        Conversation.user_id == user_id
    ).first()
    if conv and conv.state_json:
        try:
            return json.loads(conv.state_json)
        except json.JSONDecodeError:
            pass
    return {"mode": None, "booking": {}}

class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, time, datetime)):
            return obj.isoformat()
        return super().default(obj)

def save_session(db: Session, session_id: str, user_id: str, state: dict[str, Any]) -> None:
    conv = db.query(Conversation).filter(
        Conversation.session_id == session_id,
        Conversation.user_id == user_id
    ).first()
    if not conv:
        conv = Conversation(session_id=session_id, user_id=user_id)
        db.add(conv)
    conv.state_json = json.dumps(state, cls=DateTimeEncoder)
    conv.updated_at = datetime.now(UTC)
    db.commit()
