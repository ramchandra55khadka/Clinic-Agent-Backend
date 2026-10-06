from datetime import datetime
from typing import Any

from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from loguru import logger
from pydantic import ValidationError

from app.ai.llm_client import LLMClient, normalize_llm_text
from app.ai.prompts.appointment_agent_prompt import APPOINTMENT_HUMAN_PROMPT, APPOINTMENT_SYSTEM_PROMPT
from app.core.config import settings
from app.db.session import SessionLocal
from app.repositories import create_appointment, get_appointments_by_doctor, get_doctor_schedule
from app.schemas.appointment import AppointmentCreate
from app.services.availability import check_availability


class AppointmentAgent:
    """
    Fully chat-based LLM Appointment Booking Agent.
    - Guides user to specify doctor, date, time
    - Checks availability dynamically
    - Collects patient info
    - Books appointment in DB
    """

    def __init__(
        self,
        llm_model: str | None = None,
        temperature: float | None = None,
    ):
        logger.info("Initializing Chat-based Appointment Agent (lazy mode)...")

        self._llm_model = llm_model
        self._temperature = temperature
        self.llm: LLMClient | None = None

        # --------------------------
        # Final Prompt Template
        # --------------------------
        self.prompt_template = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(APPOINTMENT_SYSTEM_PROMPT),
            HumanMessagePromptTemplate.from_template(APPOINTMENT_HUMAN_PROMPT)
        ])

    def _get_llm(self) -> LLMClient | None:
        """Create Gemini only for the conversational branch."""
        if self.llm is not None:
            return self.llm
        if not settings.google_api_key:
            return None
        try:
            self.llm = LLMClient(model=self._llm_model, temperature=self._temperature)
        except Exception as exc:  # pragma: no cover - provider/config dependent
            logger.error(f"Appointment LLM initialization failed: {exc}")
            return None
        return self.llm

    # -----------------------------------------------------------------
    def _messages_to_dicts(self, messages) -> list[dict[str, str]]:
        """Convert LangChain messages → Gemini-safe dicts"""
        output = []
        for msg in messages:
            role = "system" if msg.type == "system" else "user"
            output.append({"role": role, "content": msg.content})
        return output

    # -----------------------------------------------------------------
    def _fallback_reply(
        self,
        doctor_id: int | None = None,
        appointment_date: str | None = None,
    ) -> str:
        if doctor_id is None:
            return "Which doctor would you like to see?"
        if appointment_date is None:
            return "What date would you like to book the appointment for?"
        return "Please share your preferred time and patient details so I can check availability."

    # -----------------------------------------------------------------
    def build_context(
        self,
        db,
        doctor_id: int | None = None,
        date: str | None = None
    ):
        """Prepare context with doctor schedule + appointments"""
        context: dict[str, Any] = {}

        if doctor_id is not None:
            schedule = get_doctor_schedule(db, doctor_id)
            logger.info(f"Fetching schedule for doctor_id={doctor_id}: {schedule}")
            if schedule:
                context["schedule"] = {
                    "doctor_id": schedule.doctor_id,
                    "doctor_name": schedule.doctor_name,
                    "start_time": str(schedule.start_time),
                    "end_time": str(schedule.end_time),
                    "break_start": str(schedule.break_start),
                    "break_end": str(schedule.break_end),
                    "leave_date": str(schedule.leave_date) if schedule.leave_date else None,
                    "slot_duration": schedule.slot_duration or 30,
                    "days": schedule.days,
                }

        if doctor_id is not None and date is not None:
            # Convert string date to datetime.date
            try:
                date_obj = datetime.strptime(date, "%Y-%m-%d").date() if isinstance(date, str) else date
            except ValueError:
                logger.info(f"Ignoring invalid appointment date in context: {date}")
                return context

            appointments = get_appointments_by_doctor(db, doctor_id)
            logger.info(f"Fetching appointments for doctor_id={doctor_id}, date={date_obj}: {appointments}")
            context["appointments"] = [
                {
                    "id": appt.id,
                    "date": str(appt.date),
                    "time": str(appt.time),
                    "patient_name": appt.patient_name
                }
                for appt in appointments if appt.date == date_obj
            ]

        return context

    # -----------------------------------------------------------------
    def answer(
        self,
        query: str,
        doctor_id: int | None = None,
        appointment_date: str | None = None
    ) -> dict[str, Any]:
        """LLM conversational response"""
        with SessionLocal() as db:
            context = self.build_context(db, doctor_id, appointment_date)

        # If doctor not provided, ask user first
        if doctor_id is None:
            logger.info("Doctor not specified by user")
            return {
                "response": "Which doctor would you like to see?",
                "context": context,
                "booking_status": None,
                "appointment": None,
                "message": "ask_doctor"
            }

        llm = self._get_llm()
        if llm is None:
            return {
                "response": self._fallback_reply(doctor_id, appointment_date),
                "context": context,
                "booking_status": None,
                "appointment": None,
                "message": "chat"
            }

        # Build prompt
        messages = self.prompt_template.format_messages(
            query=query,
            context=context
        )
        msgs = self._messages_to_dicts(messages)

        try:
            llm_resp = llm.invoke(msgs)
            reply = normalize_llm_text(llm_resp).strip() or self._fallback_reply(doctor_id, appointment_date)
        except Exception as e:
            logger.error(f"LLM error: {e}")
            reply = self._fallback_reply(doctor_id, appointment_date)

        return {
            "response": reply,
            "context": context,
            "booking_status": None,
            "appointment": None,
            "message": "chat"
        }

    # -----------------------------------------------------------------
    def try_booking(
        self,
        doctor_id: int,
        patient_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Attempt to book an appointment.
        patient_data must contain:
        - patient_name, age, sex, email, phone, date, time
        """

        payload = dict(patient_data)
        payload.pop("doctor_id", None)

        try:
            if isinstance(payload["date"], str):
                payload["date"] = datetime.strptime(payload["date"], "%Y-%m-%d").date()
            if isinstance(payload["time"], str):
                payload["time"] = datetime.strptime(payload["time"], "%H:%M").time()
            appointment = AppointmentCreate(doctor_id=doctor_id, **payload)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            return {"status": "failed", "message": f"Invalid appointment details: {exc}"}

        with SessionLocal() as db:
            # 1️⃣ Check availability
            available = check_availability(db, doctor_id, appointment.date, appointment.time)
            logger.info(f"Checking availability for doctor_id={doctor_id}, date={appointment.date}, time={appointment.time}: {available}")

            if not available:
                return {"status": "failed", "message": "Doctor not available at this slot"}

            # 2️⃣ Save appointment
            saved = create_appointment(db, appointment)
            logger.info(f"Appointment saved: {saved}")

            # 3️⃣ Return success info
            return {
                "status": "success",
                "appointment": {
                    "id": saved.id,
                    "patient_name": saved.patient_name,
                    "date": str(saved.date),
                    "time": str(saved.time)
                }
            }
