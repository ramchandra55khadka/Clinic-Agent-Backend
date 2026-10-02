"""Long-term memory listings."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.memory_keys import MEMORY_KEYS

#: The keys a user may set by hand — derived from the same tuple the chat
#: extractor writes with, so the two can never drift apart. Declared as a
#: ``Literal`` rather than a plain ``str`` so FastAPI rejects an unknown key with
#: a 422 that lists the valid ones.
MemoryKey = Literal[
    "preferred_time",
    "preferred_doctor",
    "preferred_specialty",
    "language",
    "contact_preference",
    "books_for_family",
]

#: Fails at import if the literal above and :data:`MEMORY_KEYS` ever disagree —
#: cheaper than discovering it from a 500 in production.
assert set(MemoryKey.__args__) == set(MEMORY_KEYS), "MemoryKey is out of sync with MEMORY_KEYS"


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    value: str
    kind: str
    content: str
    source: str
    confidence: float
    created_at: Any
    updated_at: Any
    last_seen_at: Any


class MemoryUpdate(BaseModel):
    value: str = Field(..., min_length=1, max_length=200)


class MemoryCreate(BaseModel):
    """Body of ``PUT /memories/{key}`` — set one preference by hand.

    ``(user, key)`` is unique, so a key that is already saved is overwritten in
    place rather than duplicated. The value must contain at least one visible
    character; to *remove* a preference use ``DELETE /memories/{id}`` instead.
    """

    key: MemoryKey
    value: str = Field(..., min_length=1, max_length=200)



class MemoryListResponse(BaseModel):
    memories: list[MemoryOut]



class MemoryClearResponse(BaseModel):
    deleted: int
