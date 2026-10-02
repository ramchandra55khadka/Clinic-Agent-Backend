"""RAG / knowledge-core query endpoints."""

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=12)
    system_prompt: str | None = None



class QueryResponse(BaseModel):
    response: str
    chunks: list[dict[str, Any]] | None = None

