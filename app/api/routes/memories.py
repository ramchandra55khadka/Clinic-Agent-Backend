"""User controls for long-term memories."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user_account import UserAccount
from app.schemas.common import MessageResponse
from app.schemas.memory import (
    MemoryClearResponse,
    MemoryCreate,
    MemoryListResponse,
    MemoryOut,
    MemoryUpdate,
)
from app.services import memory as memory_service

router = APIRouter(prefix="/memories", tags=["memories"])

#: Last-resort copy when the value policy rejects a value for a reason we did not
#: diagnose up front. Blank and medical values get the specific messages below.
_VALUE_POLICY_DETAIL = "That value cannot be saved. Use a short, non-medical preference."


@router.get("/", response_model=MemoryListResponse)
def list_my_memories(
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    return MemoryListResponse(memories=memory_service.list_memories(db, user_id=current_user.id))


@router.put("/{memory_key}", response_model=MemoryOut)
def set_my_memory(
    memory_key: str,
    payload: MemoryCreate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    """Creates or replaces one saved personalization.

    ``PUT`` because ``(user, key)`` is unique and the call is idempotent: a slot
    you have not saved yet becomes a new row (201), one you already have is
    overwritten in place (200), so there is never a duplicate to reconcile. The
    key rides in the path and is repeated in the body; a mismatch is a 422, so a
    copy-paste slip cannot quietly write a different slot.

    Values meet the same bar as everything else that reaches long-term memory —
    blank or medical wording is a 422 that says which, instead of the 404 the
    id-based ``PATCH`` gives for a row that does not exist. Removal stays on
    ``DELETE``: this endpoint only ever sets a value.
    """
    if memory_key != payload.key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Body key must match the path (got '{payload.key}', expected '{memory_key}').",
        )

    # Mirrors the checks _valid_memory applies after collapsing whitespace, so
    # the caller learns which rule it tripped rather than a single "no".
    value = " ".join(payload.value.split())
    if not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A personalization needs a value — type one before saving.",
        )
    if memory_service.HEALTH_TERMS.search(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That looks like medical information, so it is not stored. Save a preference instead.",
        )

    existed = memory_service.get_memory_by_key(db, user_id=current_user.id, key=memory_key) is not None
    memory = memory_service.upsert_memory(db, user_id=current_user.id, key=memory_key, value=value)
    if memory is None:
        # Unreachable: the key came from MEMORY_KEYS and the value cleared the
        # same rules upsert_memory enforces. Belt and braces, not a code path.
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=_VALUE_POLICY_DETAIL)

    response.status_code = status.HTTP_200_OK if existed else status.HTTP_201_CREATED
    return memory


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_my_memory(
    memory_id: str,
    payload: MemoryUpdate,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    """Rewrite the value of one saved preference.

    A missing (or not-owned) id is a 404. An existing memory whose *new* value
    the policy rejects — the extractor never stores medical terms — is a 422,
    so the profile UI can say what was wrong instead of pretending the row
    vanished. Without the lookup first, both cases come back from the service
    as ``None`` and every rejected edit would look like a deleted memory.
    """
    if memory_service.get_memory(db, user_id=current_user.id, memory_id=memory_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    memory = memory_service.update_memory(db, user_id=current_user.id, memory_id=memory_id, value=payload.value)
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That value cannot be saved. Use a short, non-medical preference.",
        )
    return memory


@router.delete("/{memory_id}", response_model=MessageResponse)
def delete_my_memory(
    memory_id: str,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    if not memory_service.delete_memory(db, user_id=current_user.id, memory_id=memory_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return MessageResponse(message="Memory deleted")


@router.delete("/", response_model=MemoryClearResponse)
def clear_my_memories(
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    return MemoryClearResponse(deleted=memory_service.clear_memories(db, user_id=current_user.id))
