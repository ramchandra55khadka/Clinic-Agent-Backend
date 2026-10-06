"""Deterministic handling for standalone chat control messages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.schemas.chat import ChatResponse

SimpleAction = Literal["respond", "cancel", "confirm_positive", "confirm_negative"]


@dataclass(frozen=True)
class SimpleMessageResult:
    response: str
    action: SimpleAction = "respond"
    intent: Literal["fallback"] = "fallback"
    data: dict[str, Any] | None = None


_HELP_RESPONSE = (
    "I can help you with doctor information, clinic FAQs, doctor availability, "
    "appointment booking, appointment changes, and your appointment details."
)
_IDENTITY_RESPONSE = (
    "I am the clinic assistant. I can help with doctor information, availability, "
    "and appointment booking."
)
_REPEAT_RESPONSE = "Would you like me to repeat my previous response?"
_CANCEL_RESPONSE = "Okay, I have cancelled the current request."
_YES_RESPONSE = "Okay, I will continue."
_NO_RESPONSE = "Okay, I will stop that request."

_RESPONSES: dict[str, str] = {
    "greeting": "Hi there, how can I help you today?",
    "goodbye": "Goodbye! Take care.",
    "thanks": "You're welcome!",
    "ack": "Okay!",
    "positive_feedback": "Glad I could help!",
    "help": _HELP_RESPONSE,
    "identity": _IDENTITY_RESPONSE,
    "repeat": _REPEAT_RESPONSE,
}

_PHRASES: dict[str, set[str]] = {
    "greeting": {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "namaste"},
    "goodbye": {"bye", "bye bye", "goodbye", "see you", "see you later", "take care"},
    "thanks": {"thanks", "thank you", "thanks a lot", "appreciate it"},
    "ack": {"okay", "ok", "alright", "got it", "understood", "sure"},
    "positive": {"yes", "yeah", "yep", "correct", "that's right", "that is right"},
    "negative": {"no", "nope", "not really"},
    "help": {"help", "what can you do", "how can you help me"},
    "identity": {"who are you", "what are you", "are you an ai", "are you a bot"},
    "positive_feedback": {
        "great",
        "nice",
        "nice to meet you",
        "nice to see you",
        "perfect",
        "awesome",
        "excellent",
    },
    "repeat": {"repeat", "say that again", "can you repeat", "i didn't understand", "i did not understand"},
    "cancel": {"cancel", "stop", "never mind", "nevermind", "forget it"},
}


def _normalize(message: str) -> str:
    normalized = message.strip().lower()
    normalized = re.sub(r"[.!?:,;]+$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _greeting_response(user_name: str | None) -> str:
    """A warm, personalized opener.

    Patients are greeted by name when we know it, and with a friendly generic
    line otherwise (e.g. an account that has not filled in a profile yet).
    """
    name = (user_name or "").strip()
    if name:
        return f"Hi {name}, how can I help you today?"
    return _RESPONSES["greeting"]


def _is_waiting_for_confirmation(conversation_state: dict[str, Any]) -> bool:
    return bool(
        conversation_state.get("awaiting_confirmation")
        or conversation_state.get("waiting_for_confirmation")
        or conversation_state.get("requires_confirmation")
        or conversation_state.get("confirmation")
    )


def simple_message_response(
    message: str,
    *,
    session_id: str,
    conversation_state: dict[str, Any] | None = None,
    user_name: str | None = None,
) -> tuple[ChatResponse, dict[str, Any]] | None:
    """Return a deterministic response for standalone simple messages.

    The match is intentionally exact after lowercasing, whitespace collapsing,
    and stripping trailing sentence punctuation. Mixed messages such as
    "Hi, I want to book" do not match and continue through the normal workflow.

    ``user_name`` personalizes the greeting only; every other reply is static.
    """
    text = _normalize(message)
    state = conversation_state or {"mode": None, "booking": {}}

    if state.get("mode") == "booking" and _is_waiting_for_confirmation(state):
        if text in _PHRASES["positive"] or text in _PHRASES["negative"]:
            return None

    for category in ("greeting", "goodbye", "thanks", "ack", "help", "identity", "positive_feedback", "repeat"):
        if text in _PHRASES[category]:
            return (
                ChatResponse(
                    session_id=session_id,
                    intent="fallback",
                    response=_greeting_response(user_name) if category == "greeting" else _RESPONSES[category],
                    data={"simple_message": category},
                    chunks=None,
                ),
                state,
            )

    if text in _PHRASES["cancel"]:
        next_state = {"mode": None, "booking": {}}
        return (
            ChatResponse(
                session_id=session_id,
                intent="fallback",
                response=_CANCEL_RESPONSE if state.get("mode") else "Okay.",
                data={"simple_message": "cancel", "cancelled": bool(state.get("mode"))},
                chunks=None,
            ),
            next_state,
        )

    if text in _PHRASES["positive"] and _is_waiting_for_confirmation(state):
        next_state = {**state, "awaiting_confirmation": False, "confirmed": True}
        return (
            ChatResponse(
                session_id=session_id,
                intent="fallback",
                response=_YES_RESPONSE,
                data={"simple_message": "positive", "confirmed": True},
                chunks=None,
            ),
            next_state,
        )

    if text in _PHRASES["negative"] and _is_waiting_for_confirmation(state):
        next_state = {"mode": None, "booking": {}}
        return (
            ChatResponse(
                session_id=session_id,
                intent="fallback",
                response=_NO_RESPONSE,
                data={"simple_message": "negative", "confirmed": False},
                chunks=None,
            ),
            next_state,
        )

    return None
