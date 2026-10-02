"""Long-term memory listings."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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



class MemoryListResponse(BaseModel):
    memories: list[MemoryOut]



class MemoryClearResponse(BaseModel):
    deleted: int
