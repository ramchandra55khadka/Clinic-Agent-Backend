from copy import deepcopy
from typing import Any

_sessions: dict[str, dict[str, Any]] = {}


def get_session(session_id: str) -> dict[str, Any]:
    return deepcopy(_sessions.get(session_id, {"mode": None, "booking": {}}))


def save_session(session_id: str, state: dict[str, Any]) -> None:
    _sessions[session_id] = deepcopy(state)


def clear_booking(session_id: str) -> None:
    session = _sessions.setdefault(session_id, {"mode": None, "booking": {}})
    session["mode"] = None
    session["booking"] = {}
