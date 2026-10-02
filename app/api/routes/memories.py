"""User controls for long-term memories."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user_account import UserAccount
from app.schemas.common import MessageResponse
from app.schemas.memory import MemoryClearResponse, MemoryListResponse, MemoryOut, MemoryUpdate
from app.services import memory as memory_service

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("/", response_model=MemoryListResponse)
def list_my_memories(
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    return MemoryListResponse(memories=memory_service.list_memories(db, user_id=current_user.id))


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_my_memory(
    memory_id: str,
    payload: MemoryUpdate,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    memory = memory_service.update_memory(db, user_id=current_user.id, memory_id=memory_id, value=payload.value)
    if memory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
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
