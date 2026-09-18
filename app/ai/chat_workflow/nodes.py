from datetime import datetime
from typing import Any

from loguru import logger
from pydantic import ValidationError

from app.ai.agents.qa_agent import RAGAgent
from app.ai.chat_workflow.extraction import FIELD_QUESTIONS, extract_booking_fields, missing_fields
from app.ai.chat_workflow.memory import clear_booking, save_session
from app.ai.chat_workflow.state import ClinicChatState
from app.ai.mcp.mcp_tools import book_appointment, check_slots, explain_slot
from app.database.schema import AppointmentCreate

_rag_agent: RAGAgent | None = None


def _get_rag_agent() -> RAGAgent:
    global _rag_agent
    if _rag_agent is None:
        logger.info("Initializing shared RAG agent")
        _rag_agent = RAGAgent(
            docs_dir="docs",
            persist_dir="vector_db/faiss",
            llm_model="gemini-2.5-flash",
            temperature=0.3,
            top_k=5,
        )
    return _rag_agent


def serialize_chunks(docs) -> list[dict[str, Any]]:
    return [
        {
            "content": doc.page_content,
            "source": doc.metadata.get("source"),
            "page": doc.metadata.get("page"),
            "chunk_id": doc.metadata.get("chunk_id"),
        }
        for doc in docs
    ]


def route_intent(state: ClinicChatState) -> dict:
    conversation = state.get("conversation", {})
    if conversation.get("mode") == "booking":
        return {"intent": "booking"}
    if state.get("patient"):
        return {"intent": "booking"}

    text = state["message"].lower()
    appointment_words = (
        "appointment",
        "available",
        "availability",
        "book",
        "schedule",
        "slot",
        "free",
        "visit",
        "consult",
    )
    if any(word in text for word in appointment_words):
        return {"intent": "booking"}

    bio_words = (
        "doctor",
        "dr.",
        "bio",
        "experience",
        "qualification",
        "specialization",
        "education",
        "about",
    )
    if any(word in text for word in bio_words):
        return {"intent": "doctor_bio"}

    if text.strip().isdigit():
        return {"intent": "fallback"}

    return {"intent": "doctor_bio"}


def doctor_bio_node(state: ClinicChatState) -> dict:
    agent = _get_rag_agent()
    result = agent.answer(query=state["message"], top_k=5)
    return {
        "response": result["response"],
        "chunks": serialize_chunks(result.get("chunks", [])),
        "data": {},
    }


def availability_node(state: ClinicChatState) -> dict:
    doctor_id = state.get("doctor_id")
    appointment_date = state.get("appointment_date")
    appointment_time = state.get("appointment_time")

    if not doctor_id:
        return {
            "response": FIELD_QUESTIONS["doctor_id"],
            "data": {"required": ["doctor_id"]},
        }
    if not appointment_date:
        return {
            "response": FIELD_QUESTIONS["date"],
            "data": {"required": ["appointment_date"]},
        }

    slots = check_slots(doctor_id, appointment_date)
    if not slots:
        return {
            "response": "I could not find a schedule for that doctor.",
            "data": {"doctor_id": doctor_id},
        }

    if appointment_time:
        reason = explain_slot(doctor_id, appointment_date, appointment_time)
        if reason is None:
            return {
                "response": "That slot is available. I can book it now. What is the patient name?",
                "data": {
                    "available": True,
                    "doctor_id": doctor_id,
                    "date": str(appointment_date),
                    "time": str(appointment_time),
                    "next_step": "booking_chat",
                },
            }
        return {
            "response": "That slot is not available. Please choose another available time.",
            "data": {"available": False, "reason": reason, "slots": slots},
        }

    return {
        "response": "Here are the available appointment slots. Which time would you like?",
        "data": {
            "available": any(slot["available"] for slot in slots),
            "doctor_id": doctor_id,
            "date": str(appointment_date),
            "slots": slots,
        },
    }


def _format_available_times(slots: list[dict[str, Any]]) -> str:
    available = [str(slot["time"])[:5] for slot in slots if slot.get("available")]
    if not available:
        return "No slots are available for that date."
    return "Available times: " + ", ".join(available[:12])


def booking_node(state: ClinicChatState) -> dict:
    session_id = state["session_id"]
    conversation = state.get("conversation", {"mode": None, "booking": {}})
    booking = conversation.get("booking", {})
    booking = extract_booking_fields(state["message"], booking)

    if state.get("doctor_id") and not booking.get("doctor_id"):
        booking["doctor_id"] = state["doctor_id"]
    if state.get("appointment_date") and not booking.get("date"):
        booking["date"] = str(state["appointment_date"])
    if state.get("appointment_time") and not booking.get("time"):
        booking["time"] = str(state["appointment_time"])[:5]

    conversation["mode"] = "booking"
    conversation["booking"] = booking
    save_session(session_id, conversation)

    missing = missing_fields(booking)
    if "doctor_id" not in missing and "date" not in missing:
        slots = check_slots(int(booking["doctor_id"]), datetime.strptime(booking["date"], "%Y-%m-%d").date())
        if not slots:
            return {
                "response": "I could not find a schedule for that doctor. Please provide another doctor ID.",
                "data": {"booking": booking, "required": ["doctor_id"]},
            }
        if "time" in missing:
            return {
                "response": _format_available_times(slots) + " Which time should I book?",
                "data": {"booking": booking, "slots": slots, "required": ["time"]},
            }

    if missing:
        next_field = missing[0]
        return {
            "response": FIELD_QUESTIONS[next_field],
            "data": {"booking": booking, "required": [next_field]},
        }

    try:
        appointment = AppointmentCreate(
            doctor_id=int(booking["doctor_id"]),
            patient_name=booking["patient_name"],
            age=int(booking["age"]),
            sex=booking["sex"],
            email=booking["email"],
            phone=booking["phone"],
            date=datetime.strptime(booking["date"], "%Y-%m-%d").date(),
            time=datetime.strptime(booking["time"], "%H:%M").time(),
        )
    except (ValueError, ValidationError) as exc:
        return {
            "response": "Some appointment details look invalid. Please send the date as YYYY-MM-DD and time like 10:30 AM.",
            "data": {"booking": booking, "error": str(exc)},
        }

    result = book_appointment(appointment)
    if result["status"] != "success":
        reason = result.get("reason", "unavailable")
        if reason in {"slot_booked", "during_break", "after_working_hours", "before_working_hours", "doctor_on_leave"}:
            slots = check_slots(appointment.doctor_id, appointment.date)
            booking.pop("time", None)
            conversation["booking"] = booking
            save_session(session_id, conversation)
            return {
                "response": f"That time is not available ({reason}). " + _format_available_times(slots) + " Which time should I book?",
                "data": {"booking": booking, "reason": reason, "slots": slots, "required": ["time"]},
            }
        return {
            "response": "Sorry, I could not book that appointment. Please try another slot.",
            "data": result,
        }

    clear_booking(session_id)
    appt = result["appointment"]
    return {
        "response": (
            f"Your appointment is confirmed for {appt['date']} at {appt['time']}. "
            f"The confirmation email status is {appt.get('email_status', 'pending')}."
        ),
        "data": result,
    }


def fallback_node(state: ClinicChatState) -> dict:
    return {
        "response": "I can help with doctor information, availability, and appointment booking.",
        "data": {},
    }


def choose_node(state: ClinicChatState) -> str:
    return state.get("intent", "fallback")
