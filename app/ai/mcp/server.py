from fastapi import APIRouter, Depends

from app.ai.mcp.mcp_tools import book_appointment, check_slots, explain_slot
from app.ai.mcp.schema import MCPAvailabilityRequest, MCPBookAppointmentRequest
from app.dependencies.auth import get_current_user

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.post("/check-availability")
def mcp_check_availability(request: MCPAvailabilityRequest, _user=Depends(get_current_user)):
    slots = check_slots(request.doctor_id, request.date)
    reason = None
    if request.time is not None:
        reason = explain_slot(request.doctor_id, request.date, request.time)
    return {
        "available": reason is None if request.time is not None else any(slot["available"] for slot in slots),
        "reason": reason,
        "slots": slots,
    }


@router.post("/book-appointment")
def mcp_book_appointment(request: MCPBookAppointmentRequest, _user=Depends(get_current_user)):
    return book_appointment(request.appointment)
