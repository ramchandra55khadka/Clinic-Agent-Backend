"""Doctor info endpoints (RAG + the LangGraph chat workflow).

Both require an authenticated caller: chat can disclose clinic knowledge and
trigger bookings, so it must never be open to anonymous traffic.
"""

import re
from datetime import datetime
from difflib import SequenceMatcher
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from app import repositories
from app.ai.chat_workflow.graph import run_clinic_chat, run_rag
from app.ai.chat_workflow.memory import get_session, save_session
from app.ai.chat_workflow.simple_messages import simple_message_response
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.days import column_to_days
from app.db.session import SessionLocal, get_db
from app.models.doctor import Doctor
from app.models.user_account import UserAccount
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.query import QueryRequest, QueryResponse
from app.services import memory as memory_service

router = APIRouter(tags=["doctor-info"])


def _extract_memories_background(user_id: str, session_id: str, message: str) -> None:
    with SessionLocal() as db:
        user = db.get(UserAccount, user_id)
        if user is None or not memory_service.memory_enabled(db, user):
            return
        conversation = memory_service.get_conversation(db, session_id=session_id, user_id=user_id)
        if conversation is None:
            return
        user_turns = sum(1 for row in memory_service.list_messages(db, session_id=session_id, user_id=user_id) if row.role == "user")
        if user_turns % 4 != 0:
            return
        memory_service.extract_memories_from_message(
            db,
            user=user,
            message=message,
            source_conversation_id=conversation.id,
        )


def _refresh_summary_background(session_id: str, user_id: str) -> None:
    with SessionLocal() as db:
        memory_service.refresh_summary(db, session_id=session_id, user_id=user_id)


def _link_chat_booking_to_account(db: Session, user: UserAccount, response: ChatResponse) -> None:
    """A booking made in chat belongs to the session's account.

    Links the fresh appointment to the account's patient row so tracking and
    the self-service endpoints resolve through the account — never through the
    email the patient happened to type during the conversation.
    """
    data = response.data or {}
    if data.get("status") != "success":
        return
    appointment_id = (data.get("appointment") or {}).get("id")
    if not appointment_id:
        return
    appointment = repositories.get_appointment(db, appointment_id)
    if appointment is None or appointment.patient_id is not None:
        return
    patient = repositories.ensure_patient_for_user(db, user)
    appointment.patient_id = patient.id
    db.commit()


def _looks_like_my_appointments_question(message: str) -> bool:
    text = " ".join(message.lower().split())
    if not any(term in text for term in ("appointment", "booking", "visit", "schedule")):
        return False
    if any(term in text for term in ("history", "record", "records", "my appointment", "my booking", "upcoming", "next", "previous", "past", "list", "show")):
        return True
    if any(term in text for term in ("do i have", "have i booked", "when is my")):
        return True
    return text in {"appointments", "bookings", "my visits"}


def _doctor_name(appointment) -> str:
    doctor = getattr(appointment, "doctor", None)
    profile = getattr(doctor, "profile", None)
    name = getattr(profile, "display_name", None)
    if name:
        return name
    return f"Doctor #{appointment.doctor_id}"


def _appointment_item(appointment) -> dict:
    return {
        "id": appointment.id,
        "doctor_id": appointment.doctor_id,
        "doctor_name": _doctor_name(appointment),
        "patient_name": appointment.patient_name,
        "age": appointment.age,
        "sex": appointment.sex,
        "email": appointment.email,
        "phone": appointment.phone,
        "date": appointment.date.isoformat(),
        "time": appointment.time.isoformat(),
        "status": appointment.status,
        "confirmation_email_status": appointment.confirmation_email_status,
    }


def _format_appointment_history(items: list[dict]) -> str:
    if not items:
        return "I could not find any appointments linked to your account."

    now = datetime.now(settings.clinic_tzinfo)
    upcoming = []
    past = []
    cancelled = []
    for item in items:
        when = datetime.fromisoformat(f"{item['date']}T{item['time']}").replace(tzinfo=settings.clinic_tzinfo)
        if item["status"] == "cancelled":
            cancelled.append(item)
        elif when >= now:
            upcoming.append(item)
        else:
            past.append(item)

    def line(item: dict) -> str:
        return (
            f"- #{item['id']} · {item['doctor_name']} · {item['date']} at {item['time'][:5]} · "
            f"{item['patient_name']} ({item['age']}, {item['sex']}) · "
            f"contact: {item['email']}, {item['phone']} · "
            f"status: {item['status']} · confirmation email: {item['confirmation_email_status']}"
        )

    sections = ["Here are the appointment records linked to your account."]
    if upcoming:
        sections.append("\nUpcoming\n" + "\n".join(line(item) for item in upcoming[:8]))
    if past:
        sections.append("\nPast\n" + "\n".join(line(item) for item in past[:8]))
    if cancelled:
        sections.append("\nCancelled\n" + "\n".join(line(item) for item in cancelled[:8]))
    sections.append("\nNext: Ask for a specific appointment number if you want details, or open My appointments to edit/cancel.")
    return "\n".join(sections)


def _appointment_history_response(message: str, session_id: str, db: Session, current_user: UserAccount) -> ChatResponse | None:
    if not _looks_like_my_appointments_question(message):
        return None
    appointments = repositories.get_appointments_for_user(db, current_user)
    items = [_appointment_item(appointment) for appointment in appointments]
    return ChatResponse(
        session_id=session_id,
        intent="booking",
        response=_format_appointment_history(items),
        data={"source": "database", "appointments": items, "count": len(items)},
        chunks=None,
    )


def _looks_like_doctor_database_question(message: str) -> bool:
    text = " ".join(message.lower().split())
    if not any(term in text for term in ("doctor", "doctors", "physician", "specialist")):
        return False
    if any(term in text for term in ("available", "availability", "free slot", "slots")):
        return False
    return any(
        term in text
        for term in (
            "tell me",
            "show",
            "list",
            "detail",
            "details",
            "profile",
            "qualification",
            "education",
            "experience",
            "specialization",
            "fee",
            "schedule",
            "available",
            "about",
            "our doctor",
            "our doctors",
            "doctor id",
        )
    )


def _normalize_doctor_text(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    stopwords = {
        "about",
        "detail",
        "details",
        "doctor",
        "dr",
        "me",
        "please",
        "profile",
        "show",
        "tell",
    }
    return " ".join(word for word in words if word not in stopwords)


def _doctor_matches(message: str, doctor: Doctor) -> bool:
    text = message.lower()
    profile = doctor.profile
    name = (profile.full_name if profile else "").lower()
    if f"doctor id {doctor.id}" in text or f"doctor #{doctor.id}" in text or f"dr {doctor.id}" in text:
        return True
    if name and all(part in text for part in name.split()):
        return True
    if profile and profile.first_name and profile.first_name.lower() in text:
        return True
    return False


def _doctor_name_similarity(message: str, doctor: Doctor) -> float:
    profile = doctor.profile
    if not profile:
        return 0
    query = _normalize_doctor_text(message)
    name = _normalize_doctor_text(profile.full_name)
    if not query or not name:
        return 0
    return max(
        SequenceMatcher(None, query, name).ratio(),
        *(
            SequenceMatcher(None, token, name_token).ratio()
            for token in query.split()
            for name_token in name.split()
        ),
    )


def _doctor_name_suggestions(message: str, doctors: list[Doctor]) -> list[Doctor]:
    if _looks_like_doctor_database_question(message):
        return []
    text = " ".join(message.lower().split())
    if not any(term in text for term in ("tell me", "about", "detail", "details", "profile", "who is")):
        return []
    scored = [
        (_doctor_name_similarity(message, doctor), doctor)
        for doctor in doctors
        if getattr(doctor, "profile", None) is not None
    ]
    scored = [(score, doctor) for score, doctor in scored if score >= 0.78]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [doctor for _score, doctor in scored[:3]]


def _education_item(education) -> dict:
    return {
        "id": education.id,
        "degree": education.degree,
        "institution": education.institution,
        "field_of_study": education.field_of_study,
        "start_date": education.start_date.isoformat() if education.start_date else None,
        "end_date": education.end_date.isoformat() if education.end_date else None,
        "description": education.description,
    }


def _schedule_item(schedule) -> dict:
    return {
        "schedule_id": schedule.id,
        "start_time": schedule.start_time.isoformat(),
        "end_time": schedule.end_time.isoformat(),
        "break_start": schedule.break_start.isoformat() if schedule.break_start else None,
        "break_end": schedule.break_end.isoformat() if schedule.break_end else None,
        "leave_date": schedule.leave_date.isoformat() if schedule.leave_date else None,
        "slot_duration": schedule.slot_duration,
        "days": column_to_days(schedule.working_days),
    }


def _doctor_item(doctor: Doctor) -> dict:
    profile = doctor.profile
    return {
        "id": doctor.id,
        "doctor_name": profile.full_name if profile else f"Doctor #{doctor.id}",
        "first_name": profile.first_name if profile else None,
        "last_name": profile.last_name if profile else None,
        "email": profile.email if profile else None,
        "phone": profile.phone if profile else None,
        "gender": profile.gender if profile else None,
        "address": profile.address if profile else None,
        "photo_url": profile.photo_url if profile else None,
        "license_number": doctor.license_number,
        "specialization": doctor.specialization,
        "qualification": doctor.qualification,
        "experience_years": doctor.experience_years,
        "bio": doctor.bio,
        "consultation_fee": doctor.consultation_fee,
        "consultation_duration": doctor.consultation_duration,
        "is_verified": doctor.is_verified,
        "educations": [_education_item(education) for education in doctor.educations],
        "schedules": [_schedule_item(schedule) for schedule in doctor.schedules],
    }


def _format_doctors(doctors: list[dict]) -> str:
    if not doctors:
        return "I could not find any doctors in the clinic database."

    names = ", ".join(doctor["doctor_name"] for doctor in doctors)
    return f"Here are the doctor details from the clinic database: {names}."


def _personal_name_response(
    message: str, session_id: str, db: Session, current_user: UserAccount
) -> ChatResponse | None:
    """Remember the patient's name, or recall it when asked.

    Runs before the workflow so an introduction like "My name is Sarmila" is
    acknowledged and stored instead of being bounced as out-of-scope, and
    "what is my name?" is answered from long-term memory (falling back to the
    profile name for patients who never stated it in chat).
    """
    stated = memory_service.stated_name(message)
    if stated is not None:
        conversation = memory_service.get_or_create_conversation(
            db, session_id=session_id, user_id=current_user.id
        )
        memory_service.upsert_memory(
            db,
            user_id=current_user.id,
            key="name",
            value=stated,
            source_conversation_id=conversation.id,
        )
        return ChatResponse(
            session_id=session_id,
            intent="fallback",
            response=f"Nice to meet you, {stated}! I'll remember your name. How can I help you today?",
            data={"memory": {"key": "name", "value": stated}},
            chunks=None,
        )

    if not memory_service.is_name_question(message):
        return None

    name = memory_service.saved_name(db, user_id=current_user.id)
    if name is None:
        profile = repositories.get_profile_by_user_id(db, current_user.id)
        name = (profile.full_name if profile else "") or None

    if name:
        return ChatResponse(
            session_id=session_id,
            intent="fallback",
            response=f"Your name is {name}.",
            data={"memory": {"key": "name", "value": name}},
            chunks=None,
        )
    return ChatResponse(
        session_id=session_id,
        intent="fallback",
        response='I don\'t know your name yet. Tell me with "My name is …" and I\'ll remember it.',
        data={"name_known": False},
        chunks=None,
    )


def _doctor_database_response(message: str, session_id: str, db: Session) -> ChatResponse | None:
    doctors = db.query(Doctor).all()
    matched = [doctor for doctor in doctors if _doctor_matches(message, doctor)]
    suggestions = _doctor_name_suggestions(message, doctors) if not matched else []
    if not _looks_like_doctor_database_question(message) and not matched:
        if suggestions:
            names = [doctor.profile.full_name for doctor in suggestions if doctor.profile]
            question = "I could not find an exact doctor with that name."
            if len(names) == 1:
                question += f" Did you mean {names[0]}?"
            else:
                question += " Did you mean one of these doctors?"
            return ChatResponse(
                session_id=session_id,
                intent="doctor_bio",
                response=question,
                data={
                    "source": "database",
                    "clarification": True,
                    "clarification_options": names,
                    "required": ["doctor_name"],
                },
                chunks=None,
            )
        return None
    selected = matched or doctors
    items = [_doctor_item(doctor) for doctor in selected]
    view = "detail" if matched else "list"
    return ChatResponse(
        session_id=session_id,
        intent="doctor_bio",
        response=_format_doctors(items),
        data={"source": "database", "doctors": items, "count": len(items), "view": view},
        chunks=None,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        session_id = request.session_id or str(uuid4())
        conversation_state = get_session(db, session_id, current_user.id)
        profile = repositories.get_profile_by_user_id(db, current_user.id)
        # A name the patient gave in chat wins over the profile name, so the
        # greeting stays in step with what they actually told us.
        remembered_name = memory_service.saved_name(db, user_id=current_user.id)
        simple_result = simple_message_response(
            request.message,
            session_id=session_id,
            conversation_state=conversation_state,
            user_name=remembered_name or (profile.full_name if profile else None),
        )
        if simple_result is not None:
            result, new_state = simple_result
            save_session(db, session_id, current_user.id, new_state)
            memory_service.save_message(
                db,
                session_id=result.session_id,
                user_id=current_user.id,
                role="user",
                content=request.message,
                intent=result.intent,
            )
            memory_service.save_message(
                db,
                session_id=result.session_id,
                user_id=current_user.id,
                role="assistant",
                content=result.response,
                intent=result.intent,
            )
            return result

        personal_name = _personal_name_response(request.message, session_id, db, current_user)
        if personal_name is not None:
            save_session(db, session_id, current_user.id, conversation_state)
            memory_service.save_message(
                db,
                session_id=personal_name.session_id,
                user_id=current_user.id,
                role="user",
                content=request.message,
                intent=personal_name.intent,
            )
            memory_service.save_message(
                db,
                session_id=personal_name.session_id,
                user_id=current_user.id,
                role="assistant",
                content=personal_name.response,
                intent=personal_name.intent,
            )
            return personal_name

        appointment_history = _appointment_history_response(request.message, session_id, db, current_user)
        if appointment_history is not None:
            save_session(db, session_id, current_user.id, conversation_state)
            memory_service.save_message(
                db,
                session_id=appointment_history.session_id,
                user_id=current_user.id,
                role="user",
                content=request.message,
                intent=appointment_history.intent,
            )
            memory_service.save_message(
                db,
                session_id=appointment_history.session_id,
                user_id=current_user.id,
                role="assistant",
                content=appointment_history.response,
                intent=appointment_history.intent,
            )
            return appointment_history

        doctor_database = _doctor_database_response(request.message, session_id, db)
        if doctor_database is not None:
            save_session(db, session_id, current_user.id, conversation_state)
            memory_service.save_message(
                db,
                session_id=doctor_database.session_id,
                user_id=current_user.id,
                role="user",
                content=request.message,
                intent=doctor_database.intent,
            )
            memory_service.save_message(
                db,
                session_id=doctor_database.session_id,
                user_id=current_user.id,
                role="assistant",
                content=doctor_database.response,
                intent=doctor_database.intent,
            )
            return doctor_database

        memories = (
            memory_service.retrieve_memories(db, user_id=current_user.id, query=request.message)
            if memory_service.memory_enabled(db, current_user)
            else []
        )

        # Replay the transcript so this turn can refer to everything said before.
        # Only the recent window is loaded verbatim; anything older lives in the
        # rolling summary, which keeps long threads inside the context window.
        history = memory_service.recent_messages(
            db, session_id=session_id, user_id=current_user.id
        )
        summary = memory_service.get_summary(db, session_id=session_id, user_id=current_user.id)

        result, new_state = run_clinic_chat(
            request,
            session_id=session_id,
            conversation_state=conversation_state,
            long_term_memories=memory_service.render_memories_for_prompt(memories),
            history=history,
            summary=summary,
        )

        # A chat booking is this account's booking whatever email was typed, so
        # it is tracked through the account's patient row from now on.
        _link_chat_booking_to_account(db, current_user, result)

        save_session(db, session_id, current_user.id, new_state)

        memory_service.save_message(
            db,
            session_id=result.session_id,
            user_id=current_user.id,
            role="user",
            content=request.message,
            intent=result.intent,
        )
        memory_service.save_message(
            db,
            session_id=result.session_id,
            user_id=current_user.id,
            role="assistant",
            content=result.response,
            intent=result.intent,
        )
        background_tasks.add_task(_extract_memories_background, current_user.id, result.session_id, request.message)
        background_tasks.add_task(_refresh_summary_background, result.session_id, current_user.id)
        return result
    except Exception as exc:
        # Log the detail, return a generic message: internals stay server-side.
        logger.exception("Chat workflow failed: {}", type(exc).__name__)
        raise HTTPException(status_code=500, detail="The assistant could not process that request.") from exc


@router.post("/rag", response_model=QueryResponse)
async def rag(request: QueryRequest, _user: UserAccount = Depends(get_current_user)):
    try:
        return run_rag(request)
    except Exception as exc:
        logger.exception("RAG query failed: {}", type(exc).__name__)
        raise HTTPException(status_code=500, detail="The knowledge base could not answer that query.") from exc
