"""Long-term memory and conversation transcript services.

Two kinds of memory live here:

* ``ConversationMessage`` rows are the full, replayable transcript of a session.
  They are written on every turn and read back to build the prompt context for the
  next turn, so the assistant can refer to what was said earlier.
* ``LongTermMemory`` rows are slot-based durable preferences. They are deliberately
  small, validated, and fetched with normal database queries rather than vector
  search.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy.orm import Session

from app.ai.llm_client import LLMClient
from app.core.config import settings

#: Re-exported for callers that import it from here; the canonical list lives in
#: :mod:`app.core.memory_keys` so the API schema and the extractor cannot drift.
from app.core.memory_keys import ALLOWED_MEMORY_KEYS  # noqa: F401
from app.models.conversation import Conversation, ConversationMessage
from app.models.long_term_memory import LongTermMemory
from app.models.user_account import UserAccount
from app.models.user_profile import UserProfile

#: How many recent turns stay verbatim in the prompt before being compacted.
HISTORY_TURNS = 10
#: Hard cap on the rolling summary, so it can never crowd out the live window.
SUMMARY_MAX_CHARS = 1200
#: Medical wording is never stored: memory is for preferences, not health data.
HEALTH_TERMS = re.compile(
    r"\b("
    r"pain|fever|diagnos|medicin|tablet|allerg|"
    r"pregnan|cancer|diabet"
    r")\w*",
    re.IGNORECASE,
)


def get_or_create_conversation(db: Session, *, session_id: str, user_id: str) -> Conversation:
    conversation = db.query(Conversation).filter(Conversation.session_id == session_id, Conversation.user_id == user_id).first()
    if conversation:
        return conversation
    conversation = Conversation(session_id=session_id, user_id=user_id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def save_message(db: Session, *, session_id: str, user_id: str, role: str, content: str, intent: str | None = None) -> None:
    conversation = get_or_create_conversation(db, session_id=session_id, user_id=user_id)
    db.add(ConversationMessage(conversation_id=conversation.id, user_id=user_id, role=role, content=content, intent=intent))
    conversation.message_count = (conversation.message_count or 0) + 1
    conversation.updated_at = datetime.now(UTC)
    if not conversation.title and role == "user":
        conversation.title = _derive_title(content)
    db.commit()


# ---------------------------------------------------------------------------
# Transcript read path
# ---------------------------------------------------------------------------


def list_messages(
    db: Session,
    *,
    session_id: str,
    user_id: str,
    limit: int | None = None,
) -> list[ConversationMessage]:
    """Return the transcript for one of this user's sessions, oldest first.

    Scoped by ``user_id`` so a guessed or stale ``session_id`` can never expose
    another patient's conversation.
    """
    conversation = (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id, Conversation.user_id == user_id)
        .first()
    )
    if conversation is None:
        return []

    query = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation.id)
    query = query.order_by(ConversationMessage.id.asc())
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def list_messages_before(
    db: Session,
    *,
    session_id: str,
    user_id: str,
    before_id: int | None = None,
    limit: int = 200,
) -> list[ConversationMessage]:
    """The newest ``limit`` turns, oldest first, optionally ending before a cursor.

    A chat transcript reads from the end, so this is what backs both the initial
    thread load and "load earlier messages". ``before_id`` is a message id, which
    stays stable across inserts and needs no offset arithmetic.
    """
    conversation = (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id, Conversation.user_id == user_id)
        .first()
    )
    if conversation is None:
        return []

    query = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conversation.id)
    if before_id is not None:
        query = query.filter(ConversationMessage.id < before_id)
    rows = query.order_by(ConversationMessage.id.desc()).limit(limit).all()
    rows.reverse()
    return rows


def has_messages_before(
    db: Session,
    *,
    session_id: str,
    user_id: str,
    before_id: int,
) -> bool:
    """Whether any turn older than ``before_id`` exists in this thread."""
    conversation = (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id, Conversation.user_id == user_id)
        .first()
    )
    if conversation is None:
        return False
    return (
        db.query(ConversationMessage.id)
        .filter(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.id < before_id,
        )
        .first()
        is not None
    )


def recent_messages(
    db: Session,
    *,
    session_id: str,
    user_id: str,
    limit: int = HISTORY_TURNS * 2,
) -> list[dict[str, str]]:
    """The newest ``limit`` messages as ``{role, content}`` dicts, oldest first."""
    rows = list_messages_before(db, session_id=session_id, user_id=user_id, limit=limit)
    return [{"role": row.role, "content": row.content} for row in rows]


def get_summary(db: Session, *, session_id: str, user_id: str) -> str:
    conversation = (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id, Conversation.user_id == user_id)
        .first()
    )
    return (conversation.summary or "") if conversation else ""


def _derive_title(content: str, max_length: int = 80) -> str:
    """First user message, trimmed, used as the thread label in the sidebar."""
    cleaned = " ".join(content.split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[:max_length].rsplit(" ", 1)[0] + "…"


def build_history_block(history: list[dict[str, str]], summary: str = "") -> str:
    """Render the prior transcript as a plain-text block for a system prompt.

    Roles are prefixed so the model can tell who said what; ``Previous:`` marks
    older turns that were compacted into ``summary``.
    """
    sections: list[str] = []
    if summary.strip():
        sections.append(f"Earlier in this conversation (summary):\n{summary.strip()}")
    if history:
        turns = "\n".join(
            f"{'Patient' if item.get('role') == 'user' else 'Assistant'}: {item.get('content', '').strip()}"
            for item in history
            if (item.get("content") or "").strip()
        )
        if turns:
            sections.append(f"Previous turns:\n{turns}")
    return "\n\n".join(sections)


def summarize_transcript(summary: str, compacted: list[dict[str, str]]) -> str:
    """Fold older turns into the running summary using the LLM.

    Falls back to a truncated concatenation when no API key is configured, so the
    thread never silently loses its whole history.
    """
    transcript = build_history_block(compacted)
    if not transcript.strip():
        return summary

    llm = _summary_llm()
    if llm is None:
        combined = "\n\n".join(part for part in (summary.strip(), transcript) if part)
        return combined[-SUMMARY_MAX_CHARS:]

    prompt = (
        "Update the running summary of a clinic patient-support conversation.\n"
        "Keep it under 120 words. Preserve: what the patient wants, booked or pending "
        "appointment details (doctor, date, time), stated preferences, and any question "
        "still open. Drop small talk. Output only the updated summary.\n\n"
        f"CURRENT SUMMARY:\n{summary.strip() or '(none)'}\n\n"
        f"NEW TURNS TO FOLD IN:\n{transcript}"
    )
    try:
        updated = str(llm.invoke(prompt) or "").strip()
    except Exception as exc:  # pragma: no cover - provider/quota dependent
        logger.warning("Conversation summary generation failed: {} ({})", type(exc).__name__, exc)
        updated = ""

    if not updated:
        return summary
    return updated[:SUMMARY_MAX_CHARS]


_summary_client: LLMClient | None = None


def _summary_llm() -> LLMClient | None:
    global _summary_client
    if not settings.google_api_key:
        return None
    if _summary_client is None:
        _summary_client = LLMClient()
    return _summary_client


def refresh_summary(db: Session, *, session_id: str, user_id: str) -> str | None:
    """Compact everything older than the live window into ``Conversation.summary``.

    Runs after the assistant reply is stored, so the transcript read for the next
    turn is already windowed. Returns the new summary, or ``None`` when nothing
    needed compacting.
    """
    conversation = (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id, Conversation.user_id == user_id)
        .first()
    )
    if conversation is None:
        return None

    window = HISTORY_TURNS * 2
    # `message_count` is maintained on every write, so it stays correct for very
    # long threads where a single read cannot load the whole transcript.
    total = conversation.message_count or 0
    keep_from = total - window
    if keep_from <= 0:
        return conversation.summary

    # `list_messages` is ascending, so this is exactly the oldest `keep_from`
    # turns — the ones falling out of the live window.
    rows = list_messages(db, session_id=session_id, user_id=user_id, limit=keep_from)
    compacted = [
        {"role": row.role, "content": row.content}
        for row in rows[:keep_from]
        if (row.content or "").strip()
    ]
    if not compacted:
        return conversation.summary

    conversation.summary = summarize_transcript(conversation.summary or "", compacted)
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    return conversation.summary


# ---------------------------------------------------------------------------
# Conversation management
# ---------------------------------------------------------------------------


def list_conversations(
    db: Session,
    *,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[Conversation]:
    """This user's threads, most recently active first."""
    query = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    )
    if offset:
        query = query.offset(offset)
    return query.limit(limit).all()


def get_conversation(db: Session, *, session_id: str, user_id: str) -> Conversation | None:
    return (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id, Conversation.user_id == user_id)
        .first()
    )


def delete_conversation(db: Session, *, session_id: str, user_id: str) -> bool:
    """Delete a thread and its turns. Returns ``False`` if it was not found."""
    conversation = get_conversation(db, session_id=session_id, user_id=user_id)
    if conversation is None:
        return False
    db.delete(conversation)
    db.commit()
    return True


def rename_conversation(db: Session, *, session_id: str, user_id: str, title: str) -> Conversation | None:
    """Set a patient-chosen sidebar title for a thread.

    Returns the updated row, or ``None`` when the thread is not owned by
    ``user_id`` (the route turns that into a 404, same as replay/delete).
    ``updated_at`` is deliberately untouched: renaming is not activity, so the
    sidebar keeps its last-active ordering.
    """
    conversation = get_conversation(db, session_id=session_id, user_id=user_id)
    if conversation is None:
        return None
    conversation.title = _derive_title(title, max_length=120)
    db.commit()
    return conversation


def memory_enabled(db: Session, user: UserAccount) -> bool:
    """Whether the account has opted into long-term memory.

    The flag lives on the ``user_profile`` row, which is not joined to the
    account by a relationship, so it is looked up by ``user_id``. Accounts
    without a profile default to enabled (matching the column default).
    """
    profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    return True if profile is None else bool(profile.memory_enabled)


def _valid_memory(key: str, value: str) -> tuple[str, str] | None:
    key = key.strip()
    value = " ".join(value.strip().split())
    if key not in ALLOWED_MEMORY_KEYS:
        return None
    if not value or len(value) > 200:
        return None
    if HEALTH_TERMS.search(value):
        return None
    return key, value


def _memory_from_legacy_content(content: str) -> tuple[str, str] | None:
    """Best-effort bridge for callers/tests that still pass old free-form text."""
    text = " ".join(content.strip().strip(".").split())
    lowered = text.lower()
    if "morning" in lowered:
        return "preferred_time", "Morning appointments"
    if "afternoon" in lowered:
        return "preferred_time", "Afternoon appointments"
    if "evening" in lowered:
        return "preferred_time", "Evening appointments"
    if "email" in lowered:
        return "contact_preference", "Email"
    if any(word in lowered for word in ("phone", "sms", "text")):
        return "contact_preference", "Phone or SMS"
    if "female doctor" in lowered:
        return "preferred_doctor", "Female doctor when possible"
    if "male doctor" in lowered:
        return "preferred_doctor", "Male doctor when possible"
    return None


def upsert_memory(
    db: Session,
    *,
    user_id: str,
    key: str | None = None,
    value: str | None = None,
    content: str | None = None,
    source_conversation_id: str | None = None,
) -> LongTermMemory | None:
    if content is not None and (key is None or value is None):
        parsed = _memory_from_legacy_content(content)
        if parsed is None:
            return None
        key, value = parsed

    if key is None or value is None:
        return None

    valid = _valid_memory(key, value)
    if valid is None:
        return None
    key, value = valid

    existing = (
        db.query(LongTermMemory)
        .filter(LongTermMemory.user_id == user_id, LongTermMemory.key == key)
        .first()
    )
    if existing:
        if existing.value != value:
            existing.value = value
        if source_conversation_id is not None:
            existing.source_conversation_id = source_conversation_id
        existing.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(existing)
        return existing

    memory = LongTermMemory(
        user_id=user_id,
        key=key,
        value=value,
        source_conversation_id=source_conversation_id,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


#: Words that end a captured name (a sentence often continues after the name).
_NAME_STOPWORDS = frozenset(
    {
        "a", "an", "and", "at", "but", "by", "can", "do", "for", "from", "good",
        "here", "her", "his", "i", "in", "is", "it", "just", "like", "my", "need",
        "new", "no", "not", "of", "ok", "okay", "on", "or", "our", "please", "sorry",
        "that", "the", "their", "there", "this", "to", "want", "was", "we", "with",
        "would", "yes", "you", "your",
    }
)

#: Explicit self-introductions only. A bare "I am X" is deliberately excluded so
#: "I am from Nepal" or "I am 30" can never be mistaken for a name.
_NAME_STATEMENT_RES = (
    re.compile(r"\bmy name(?:'s| is)\s+(?P<name>[A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,2})", re.IGNORECASE),
    re.compile(r"\byou can call me\s+(?P<name>[A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,2})", re.IGNORECASE),
    re.compile(r"\b(?:please\s+)?call me\s+(?P<name>[A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,2})", re.IGNORECASE),
    re.compile(r"\bi(?:'m| am) called\s+(?P<name>[A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,2})", re.IGNORECASE),
    re.compile(r"\bi go by\s+(?P<name>[A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,2})", re.IGNORECASE),
)

#: "what is my name", "what my name is", "do you know my name", "who am I", …
_NAME_QUESTION_RE = re.compile(
    r"\bwho am i\b|\bmy name\b[^.?!]*\?|\bwhat(?:'s| is| was)?\s+my name\b|\bwhat my name\b|"
    r"\bdo you (?:know|remember) my name\b|\btell me my name\b",
    re.IGNORECASE,
)


def _clean_stated_name(raw: str) -> str | None:
    """Keep the leading run of name-like words, dropping a trailing sentence."""
    tokens: list[str] = []
    for token in raw.split():
        cleaned = token.strip(".,!?;:\"'")
        if not re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", cleaned) or cleaned.lower() in _NAME_STOPWORDS:
            break
        tokens.append(cleaned[0].upper() + cleaned[1:])
        if len(tokens) == 3:
            break
    return " ".join(tokens) or None


def stated_name(message: str) -> str | None:
    """The name a patient just introduced themselves with, or ``None``.

    Only explicit phrasings count ("my name is…", "call me…"), never a bare
    "I am …", so a stray "I am from Nepal" cannot overwrite the real name.
    """
    for pattern in _NAME_STATEMENT_RES:
        match = pattern.search(message)
        if match:
            name = _clean_stated_name(match.group("name"))
            if name:
                return name
    return None


def is_name_question(message: str) -> bool:
    """True when the patient is asking us to recall their name."""
    return bool(_NAME_QUESTION_RE.search(message))


def saved_name(db: Session, *, user_id: str) -> str | None:
    """The name the patient asked us to remember, if any."""
    memory = get_memory_by_key(db, user_id=user_id, key="name")
    return memory.value if memory else None


def _extract_memory_candidates(message: str) -> list[tuple[str, str]]:
    """Deterministic first-pass extraction for durable preferences.

    This intentionally avoids saving transient symptoms or one-off appointment
    details. LLM structured extraction can call `upsert_memory` with the same
    allowed keys later.
    """
    lowered = message.lower()
    if HEALTH_TERMS.search(message):
        return []

    candidates: list[tuple[str, str]] = []

    name = stated_name(message)
    if name:
        candidates.append(("name", name))

    if re.search(r"\bprefer\b|\blike\b|\bworks best\b", lowered):
        if "morning" in lowered:
            candidates.append(("preferred_time", "Morning appointments"))
        if "afternoon" in lowered:
            candidates.append(("preferred_time", "Afternoon appointments"))
        if "evening" in lowered:
            candidates.append(("preferred_time", "Evening appointments"))
        if "female doctor" in lowered or "female physician" in lowered:
            candidates.append(("preferred_doctor", "Female doctor when possible"))
        if "male doctor" in lowered or "male physician" in lowered:
            candidates.append(("preferred_doctor", "Male doctor when possible"))

    if "remind me" in lowered and "email" in lowered:
        candidates.append(("contact_preference", "Email"))
    if "remind me" in lowered and any(word in lowered for word in ("phone", "sms", "text")):
        candidates.append(("contact_preference", "Phone or SMS"))
    if re.search(r"\b(nepali|english|hindi)\b", lowered) and re.search(r"\b(prefer|language|speak)\b", lowered):
        language = re.search(r"\b(nepali|english|hindi)\b", lowered)
        if language:
            candidates.append(("language", language.group(1).title()))

    seen: set[tuple[str, str]] = set()
    unique = []
    for candidate in candidates:
        if candidate not in seen and _valid_memory(*candidate):
            seen.add(candidate)
            unique.append(candidate)
    return unique


def extract_memories_from_message(
    db: Session,
    *,
    user: UserAccount,
    message: str,
    source_conversation_id: str | None = None,
) -> list[LongTermMemory]:
    if not memory_enabled(db, user):
        return []

    saved: list[LongTermMemory] = []
    for key, value in _extract_memory_candidates(message):
        memory = upsert_memory(
            db,
            user_id=user.id,
            key=key,
            value=value,
            source_conversation_id=source_conversation_id,
        )
        if memory:
            saved.append(memory)
    return saved


def retrieve_memories(db: Session, *, user_id: str, query: str, limit: int = 5) -> list[LongTermMemory]:
    del query
    memories = list_memories(db, user_id=user_id)[:limit]
    now = datetime.now(UTC)
    for memory in memories:
        memory.last_used_at = now
    if memories:
        db.commit()
    return memories


def list_memories(db: Session, *, user_id: str) -> list[LongTermMemory]:
    return (
        db.query(LongTermMemory)
        .filter(LongTermMemory.user_id == user_id)
        .order_by(LongTermMemory.updated_at.desc())
        .all()
    )


def get_memory(db: Session, *, user_id: str, memory_id: str) -> LongTermMemory | None:
    return db.query(LongTermMemory).filter(LongTermMemory.id == memory_id, LongTermMemory.user_id == user_id).first()


def get_memory_by_key(db: Session, *, user_id: str, key: str) -> LongTermMemory | None:
    """Fetch the one row for a preference slot (``uq_memory_user_key``)."""
    return db.query(LongTermMemory).filter(LongTermMemory.key == key, LongTermMemory.user_id == user_id).first()


def update_memory(db: Session, *, user_id: str, memory_id: str, value: str) -> LongTermMemory | None:
    memory = get_memory(db, user_id=user_id, memory_id=memory_id)
    if memory is None:
        return None
    valid = _valid_memory(memory.key, value)
    if valid is None:
        return None
    _key, memory.value = valid
    memory.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(memory)
    return memory


def delete_memory(db: Session, *, user_id: str, memory_id: str) -> bool:
    memory = get_memory(db, user_id=user_id, memory_id=memory_id)
    if not memory:
        return False
    db.delete(memory)
    db.commit()
    return True


def clear_memories(db: Session, *, user_id: str) -> int:
    memories = db.query(LongTermMemory).filter(LongTermMemory.user_id == user_id).all()
    for memory in memories:
        db.delete(memory)
    db.commit()
    return len(memories)


def render_memories_for_prompt(memories: list[LongTermMemory]) -> list[str]:
    labels = {
        "name": "Name",
        "preferred_doctor": "Preferred doctor",
        "preferred_specialty": "Preferred specialty",
        "preferred_time": "Preferred time",
        "language": "Language",
        "contact_preference": "Contact preference",
        "books_for_family": "Books for family",
    }
    return [f"{labels.get(memory.key, memory.key)}: {memory.value}" for memory in memories]
