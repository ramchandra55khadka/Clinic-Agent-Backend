from typing import Optional, Dict, Any, List
from loguru import logger
from datetime import datetime

from app.llm_client import LLMClient
from app.services.availability import check_availability
from app.database.crud import (
    get_doctor_schedule,
    get_appointments_by_doctor,
    create_appointment
)
from app.database.database import get_db

from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate
)


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
        llm_model: str = "gemini-2.5-flash",
        temperature: float = 0.2,
    ):
        logger.info("Initializing Chat-based Appointment Agent...")

        self.llm = LLMClient(model=llm_model, temperature=temperature)

        # --------------------------
        # System prompt
        # --------------------------
        system_prompt = """
        You are a friendly clinical appointment assistant.
        Guide users to book appointments:
        1. Ask for doctor if not provided
        2. Check doctor schedule, leave days, and existing appointments
        3. Suggest available slots only
        4. Collect patient info: name, age, sex, email, phone
        5. Confirm booking and save to database
        6. Never guess schedule
        7. Use polite, professional language
        """.strip()

        human_prompt = """
        CONTEXT:
        {context}

        USER MESSAGE:
        {query}

        Respond clearly and guide the user step by step.
        """.strip()

        self.prompt_template = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_prompt),
            HumanMessagePromptTemplate.from_template(human_prompt)
        ])

    # -----------------------------------------------------------------
    def _messages_to_dicts(self, messages) -> List[Dict[str, str]]:
        """Convert LangChain messages → Gemini-safe dicts"""
        output = []
        for msg in messages:
            role = "system" if msg.type == "system" else "user"
            output.append({"role": role, "content": msg.content})
        return output

    # -----------------------------------------------------------------
    def build_context(
        self,
        db,
        doctor_id: Optional[int] = None,
        date: Optional[str] = None
    ):
        """Prepare context with doctor schedule + appointments"""
        context: Dict[str, Any] = {}

        if doctor_id is not None:
            schedule = get_doctor_schedule(db, doctor_id)
            logger.info(f"Fetching schedule for doctor_id={doctor_id}: {schedule}")
            if schedule:
                context["schedule"] = {
                    "doctor_id": schedule.id,
                    "doctor_name": schedule.doctor_name,
                    "start_time": str(schedule.start_time),
                    "end_time": str(schedule.end_time),
                    "break_start": str(schedule.break_start),
                    "break_end": str(schedule.break_end),
                    "leave_date": str(schedule.leave_date) if schedule.leave_date else None,
                    "slot_duration": schedule.slot_duration or 30
                }

        if doctor_id is not None and date is not None:
            # Convert string date to datetime.date
            if isinstance(date, str):
                date_obj = datetime.strptime(date, "%Y-%m-%d").date()
            else:
                date_obj = date

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
        doctor_id: Optional[int] = None,
        appointment_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """LLM conversational response"""
        db = next(get_db())
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

        # Build prompt
        messages = self.prompt_template.format_messages(
            query=query,
            context=context
        )
        msgs = self._messages_to_dicts(messages)

        try:
            llm_resp = self.llm.invoke(msgs)
            reply = getattr(llm_resp, "content", str(llm_resp))
        except Exception as e:
            logger.error(f"LLM error: {e}")
            reply = "Error generating response."

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
        patient_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Attempt to book an appointment.
        patient_data must contain:
        - patient_name, age, sex, email, phone, date, time
        """

        db = next(get_db())

        # Convert date/time strings to datetime objects
        date_str = patient_data["date"]
        time_str = patient_data["time"]

        if isinstance(date_str, str):
            patient_data["date"] = datetime.strptime(date_str, "%Y-%m-%d").date()
        if isinstance(time_str, str):
            patient_data["time"] = datetime.strptime(time_str, "%H:%M").time()

        # 1️⃣ Check availability
        available = check_availability(db, doctor_id, patient_data["date"], patient_data["time"])
        logger.info(f"Checking availability for doctor_id={doctor_id}, date={patient_data['date']}, time={patient_data['time']}: {available}")

        if not available:
            return {"status": "failed", "message": "Doctor not available at this slot"}

        # 2️⃣ Save appointment
        saved = create_appointment(db, patient_data)
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
