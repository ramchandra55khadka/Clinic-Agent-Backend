from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict, Any
from loguru import logger
from app.ai.agents.appointment_agent import AppointmentAgent  # adjust path if needed

app = FastAPI(title="Chat-Based Appointment & Booking API")

# Initialize the chat-based appointment agent
agent = AppointmentAgent()


# -------------------------------
# Schemas
# -------------------------------
class PatientData(BaseModel):
    patient_name: str
    age: int
    sex: str
    email: EmailStr
    phone: str
    date: str  # YYYY-MM-DD
    time: str  # HH:MM


class ChatRequest(BaseModel):
    query: str
    doctor_id: Optional[int] = None
    appointment_date: Optional[str] = None
    patient_data: Optional[PatientData] = None  # present → attempt booking


class ChatResponse(BaseModel):
    response: str
    context: Optional[Dict[str, Any]] = None
    booking_status: Optional[str] = None
    appointment: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


# -------------------------------
# Routes
# -------------------------------
@app.get("/")
async def root():
    return {"message": "Chat & Booking API is running", "status": "healthy"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        if request.patient_data:
            patient_data_dict = (
                request.patient_data.dict() if hasattr(request.patient_data, "dict") else request.patient_data
            )

            booking_result = agent.try_booking(
                doctor_id=request.doctor_id,
                patient_data=patient_data_dict
            )

            if booking_result["status"] == "success":
                response_msg = (
                    f"Appointment booked successfully for "
                    f"{booking_result['appointment']['patient_name']} on "
                    f"{booking_result['appointment']['date']} at "
                    f"{booking_result['appointment']['time']}."
                )
            else:
                response_msg = booking_result.get("message", "Booking failed.")

            return ChatResponse(
                response=response_msg,
                booking_status=booking_result["status"],
                appointment=booking_result.get("appointment"),
                message=booking_result.get("message"),
                context=None
            )

        result = agent.answer(
            query=request.query,
            doctor_id=request.doctor_id,
            appointment_date=request.appointment_date
        )
        return ChatResponse(**result)

    except Exception as e:
        logger.error(f"Error in /chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))
