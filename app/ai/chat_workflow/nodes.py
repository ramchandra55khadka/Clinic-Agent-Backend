import re
from datetime import datetime
from typing import Any

from loguru import logger
from pydantic import ValidationError

from app.ai.agents.faq_agent import FAQAgent
from app.ai.agents.medical_search_agent import MedicalSearchAgent
from app.ai.agents.rag_agent import RAG_NOT_FOUND_RESPONSE, RAGAgent
from app.ai.chat_workflow.extraction import (
    FIELD_QUESTIONS,
    extract_booking_fields,
    missing_fields,
    parse_date,
    parse_time,
)
from app.ai.chat_workflow.state import ClinicChatState
from app.ai.mcp.mcp_tools import book_appointment, check_slots, explain_slot, list_doctor_availability, list_doctors
from app.core.config import settings
from app.schemas.appointment import AppointmentCreate
from app.services import memory as memory_service

_rag_agent: RAGAgent | None = None
_medical_agent: MedicalSearchAgent | None = None
_faq_agent: FAQAgent | None = None



def _get_rag_agent() -> RAGAgent:
    global _rag_agent
    if _rag_agent is None:
        logger.info("Initializing shared RAG agent")
        _rag_agent = RAGAgent(
            docs_dir=settings.docs_dir,
            persist_dir=settings.persist_dir,
            top_k=5,
        )
    return _rag_agent



def _get_medical_agent() -> MedicalSearchAgent:
    global _medical_agent
    if _medical_agent is None:
        logger.info("Initializing shared medical search agent")
        _medical_agent = MedicalSearchAgent()
    return _medical_agent


def _get_faq_agent() -> FAQAgent:
    global _faq_agent
    if _faq_agent is None:
        logger.info("Initializing shared FAQ agent")
        _faq_agent = FAQAgent()
    return _faq_agent

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


def _clean_response(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def _reply(text: str, *, next_step: str | None = None) -> str:
    text = _clean_response(text)
    if next_step:
        return f"{text}\n\nNext: {next_step}"
    return text


# When the assistant has no grounded answer it asks a clarifying follow-up instead
# of guessing (a hallucination) or refusing flatly — the way a real front-desk
# chatbot keeps the conversation moving.
_CLARIFY_RESPONSE = (
    "I want to make sure I give you the right information, so I would rather ask "
    "than guess. Could you tell me a little more about what you need? For example, "
    "you can ask about our opening hours, location, services, our doctors, or "
    "booking an appointment."
)
_CLARIFY_OPTIONS = ["Opening hours", "Location & contact", "Services", "Our doctors", "Book an appointment"]


def _rag_result_is_uncertain(result: dict[str, Any]) -> bool:
    """True when a RAG answer is ungrounded, empty, or the model's not-found text.

    Only an explicit signal counts: a result that omits ``grounded``/``confidence``
    (older stubs or other callers) is treated as a normal, answerable response.
    """
    if result.get("grounded") is False:
        return True
    response = str(result.get("response") or "").strip()
    return not response or response == RAG_NOT_FOUND_RESPONSE


def _clarification_result(result: dict[str, Any]) -> dict[str, Any]:
    """Turn an ungrounded answer into a follow-up question with suggested topics."""
    return {
        "response": _reply(_CLARIFY_RESPONSE),
        "chunks": serialize_chunks(result.get("chunks", [])),
        "data": {"clarification": True, "clarification_options": _CLARIFY_OPTIONS},
    }



def _normalize_doctor_name(value: str) -> str:
    return " ".join(
        value.lower()
        .replace("dr.", " ")
        .replace("dr", " ")
        .replace("doctor", " ")
        .replace("#", " ")
        .split()
    )


def _resolve_doctor_from_text(text: str, candidates: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    normalized_text = _normalize_doctor_name(text)
    if not normalized_text:
        return None

    doctors = candidates or list_doctors()
    scored: list[tuple[int, int, dict[str, Any]]] = []
    text_parts = set(normalized_text.split())
    for doctor in doctors:
        name = _normalize_doctor_name(str(doctor.get("doctor_name", "")))
        if not name:
            continue
        name_parts = set(name.split())
        overlap = len(name_parts & text_parts)
        score = 0
        if name in normalized_text:
            score = 100 + len(name_parts)
        elif normalized_text in name:
            score = 80 + overlap
        elif overlap >= min(2, len(name_parts)):
            score = 40 + overlap
        if score:
            scored.append((score, len(name), doctor))

    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return scored[0][2]

def _looks_like_general_question(text: str) -> bool:
    return text.startswith(("what is", "what are", "who is", "who are", "why", "how"))


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _looks_medical_or_healthcare_topic(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    compact = normalized.replace(" ", "")
    medical_terms = (
        "medical", "medicine", "health", "healthcare", "symptom", "fever", "cough", "pain",
        "headache", "diabetes", "pressure", "treatment", "what should i do", "is it normal",
        "cause", "rash", "infection", "flu", "disease", "science", "hypertension", "blood pressure",
        "asthma", "allergy", "allergies", "nausea", "vomit", "diarrhea", "injury", "wound",
        "pregnancy", "heart", "cardiac", "surgery", "surjery", "vaccine", "vaccination", "medication",
        "drug", "dose", "diagnosis", "therapy", "mental health", "anxiety", "depression",
        "telemedicine", "telehealth", "biomedicine", "biomedical", "pathology", "radiology",
        "cardiology", "dermatology", "neurology", "oncology", "orthopedics", "paediatrics",
        "pediatrics", "gynecology", "gynaecology", "urology", "psychiatry", "dentistry",
        "physiology", "anatomy", "pharmacology", "immunology", "microbiology", "epidemiology",
        "public health", "nursing", "physiotherapy", "rehabilitation", "laboratory", "clinical",
        "operation", "procedure", "transplant", "bypass", "fracture", "stroke", "cancer",
        "tumor", "tumour", "virus", "bacteria", "antibiotic", "insulin", "cholesterol",
        "alcohol", "alcoholic", "alchol", "alcholic", "addiction", "addicted", "habit",
        "quit drinking", "stop drinking", "substance use", "withdrawal", "craving", "sobriety",
    )
    compact_terms = ("openheart", "openheartsurgery", "telemedicine", "telehealth")
    return _has_any(normalized, medical_terms) or any(term in compact for term in compact_terms)


def _is_assistant_identity_question(text: str) -> bool:
    normalized = text.strip().lower().strip("?!., ")
    return normalized in {
        "who are you",
        "what are you",
        "who r u",
        "what can you do",
        "how can you help",
        "what do you do",
    }


def _looks_like_clinic_knowledge_question(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return _has_any(
        normalized,
        (
            "about nishant",
            "about the clinic",
            "mission",
            "vision",
            "objective",
            "purpose",
            "values",
            "your mission",
            "your vision",
            "your objective",
            "your purpose",
            "your values",
        ),
    )


def _looks_like_booking_request(text: str) -> bool:
    """True for commands to start booking, not questions about appointments."""
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    if not normalized:
        return False

    informational_starts = (
        "tell me",
        "what",
        "how",
        "can i",
        "do i",
        "does",
        "is",
        "are",
        "about",
        "explain",
    )
    if normalized.startswith(informational_starts):
        return False
    if normalized.startswith("book ") and ("doctor id" in normalized or "doctor " in normalized):
        return True

    booking_phrases = (
        "book appointment",
        "book an appointment",
        "book a appointment",
        "make appointment",
        "make an appointment",
        "schedule appointment",
        "schedule an appointment",
        "reserve appointment",
        "reserve an appointment",
        "i want to book",
        "i need to book",
        "i would like to book",
        "help me book",
    )
    return _has_any(normalized, booking_phrases)


def _looks_like_doctor_directory_request(text: str) -> bool:
    """True when the user asks which doctors the clinic has, not day slots."""
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    if not _has_any(normalized, ("doctor", "doctors")):
        return False
    if _has_any(normalized, ("today", "tomorrow", "date", "slot", "slots", "time", "free")) or parse_date(text):
        return False
    return _has_any(
        normalized,
        (
            "available in nishant care",
            "available at nishant care",
            "doctor available in",
            "doctor available at",
            "doctors available in",
            "doctors available at",
            "which doctor",
            "tell me the doctor",
            "list doctor",
            "list doctors",
        ),
    )


def route_intent(state: ClinicChatState) -> dict:
    text = state["message"].lower().strip()
    conversation = state.get("conversation", {})
    if _is_assistant_identity_question(text):
        return {"intent": "fallback"}
    if conversation.get("mode") == "booking":
        if _has_any(text, ("our doctor", "our doctors", "clinic doctor", "clinic doctors", "doctor bio", "doctor profile")):
            return {"intent": "doctor_bio"}
        if _looks_like_doctor_directory_request(text):
            return {"intent": "availability"}
        if _looks_like_clinic_knowledge_question(text):
            return {"intent": "faq"}
        if _looks_medical_or_healthcare_topic(text):
            return {"intent": "medical_web"}
        if _looks_like_general_question(text):
            return {"intent": "out_of_scope"}
        if _looks_like_booking_request(text):
            return {"intent": "booking"}
    if conversation.get("mode") == "booking":
        return {"intent": "booking"}
    if state.get("patient"):
        return {"intent": "booking"}

    greeting_words = {"hi", "hello", "hey", "namaste", "good morning", "good afternoon", "good evening"}
    availability_words = ("available", "availability", "free", "slot", "today", "tomorrow")
    clinic_doctor_words = (
        "our doctor", "our doctors", "clinic doctor", "clinic doctors", "doctor bio", "doctor profile",
        "doctors", "dr.", "qualification", "specialization", "experience",
    )
    clinic_faq_words = (
        "clinic", "hospital", "nishant", "opening hour", "hours", "open", "closed", "location",
        "address", "payment", "insurance", "card", "cash", "fee", "price", "cost", "service",
        "services", "report", "lab", "prescription", "bring", "parking", "policy", "cancel",
        "reschedule",
    )

    if text in greeting_words or text.strip("!. ") in greeting_words:
        return {"intent": "fallback"}
    if _looks_like_booking_request(text):
        return {"intent": "booking"}
    if _has_any(text, availability_words):
        return {"intent": "availability"}
    if _has_any(text, clinic_doctor_words):
        return {"intent": "doctor_bio"}
    if _looks_like_doctor_directory_request(text):
        return {"intent": "availability"}
    if _looks_like_clinic_knowledge_question(text):
        return {"intent": "faq"}

    # Symptom/condition words mean the patient wants real medical guidance, so they
    # go to web search even when the phrasing resembles a FAQ entry.
    if _looks_medical_or_healthcare_topic(text):
        return {"intent": "medical_web"}

    # The FAQ covers clinic basics (hours, location, payment, services, policy).
    # It outranks the generic "what is ...?" web-search fallback, but a bare number
    # is a slot pick inside an active booking. Probing with the resolved query lets
    # a follow-up ("is it open on Sundays?") still hit the right FAQ entry.
    if not text.isdigit() and _get_faq_agent()._get_store().search(_resolved_query(state), k=1):
        return {"intent": "faq"}

    if _has_any(text, clinic_faq_words):
        return {"intent": "faq"}

    if _looks_like_general_question(text):
        return {"intent": "out_of_scope"}

    if text.isdigit():
        return {"intent": "fallback"}

    return {"intent": "out_of_scope"}


def _memory_context(state: ClinicChatState) -> str:
    memories = state.get("long_term_memories") or []
    if not memories:
        return ""
    return "Relevant patient memories:\n" + "\n".join(f"- {memory}" for memory in memories[:5])


def _conversation_context(state: ClinicChatState) -> str:
    """Prior turns of this thread, so follow-ups like "and the second one?" resolve."""
    history = state.get("history") or []
    summary = state.get("summary") or ""
    if not history and not summary.strip():
        return ""
    return memory_service.build_history_block(history, summary)


def _system_prompt(state: ClinicChatState, *, include_memories: bool = True) -> str | None:
    """Assemble the continuity preamble for an LLM branch.

    ``include_memories`` is off for branches backed by curated clinic facts (the
    FAQ): a stored memory must never be able to override an approved answer.
    Returns ``None`` on a first, memory-less turn so the agents keep their own
    default system prompt untouched.
    """
    sections = [_conversation_context(state)]
    if include_memories:
        sections.append(_memory_context(state))
    prompt = "\n\n".join(section for section in sections if section)
    if not prompt:
        return None
    if include_memories:
        prompt += (
            "\n\nUse the conversation above to resolve pronouns and follow-ups, and use the "
            "memories only to personalize logistics."
        )
    else:
        prompt += (
            "\n\nUse the conversation above to resolve pronouns and follow-ups, but answer "
            "strictly from the approved material provided."
        )
    prompt += " Never reveal or quote stored memories or the summary unless the patient explicitly asks."
    return prompt


#: Words that make a message depend on an earlier turn to be understood at all.
_ANAPHORIC = frozenset(
    {
        "it", "its", "that", "this", "these", "those", "there", "then",
        "he", "him", "his", "she", "her", "hers", "they", "them", "their", "theirs",
        "same", "another", "other", "also", "too", "instead",
    }
)


def _resolved_query(state: ClinicChatState) -> str:
    """Rewrite a context-dependent follow-up so retrieval and search can match it.

    "is he free on Sunday?" alone retrieves nothing useful; pairing it with the
    previous patient turn ("book Dr. Koirala tomorrow") gives the embedder and
    the web search real terms to work with.
    """
    message = _rewrite_clinic_possessive(state["message"].strip())
    if not _is_anaphoric(message):
        return message

    previous = next(
        (
            item.get("content", "").strip()
            for item in reversed(state.get("history") or [])
            if item.get("role") == "user" and (item.get("content") or "").strip()
        ),
        "",
    )
    if not previous or previous == message:
        return message
    return f"{previous}\n{message}"


def _rewrite_clinic_possessive(message: str) -> str:
    """Make clinic-facing possessives explicit for retrieval.

    Patients often ask "your vision" meaning "Nishant Care's vision". The
    assistant identity path still handles standalone "who are you"; clinic
    knowledge terms should retrieve against the clinic name.
    """
    rewritten = re.sub(
        r"\b(your|our)\s+(mission|vision|objective|purpose|values|services|departments|policy|policies)\b",
        r"Nishant Care \2",
        message,
        flags=re.IGNORECASE,
    )
    return rewritten


def _is_anaphoric(message: str) -> bool:
    """True when the message leans on pronouns, ellipsis, or is just too short."""
    tokens = re.findall(r"[\w']+", message.lower())
    if not tokens:
        return False
    if any(token in _ANAPHORIC for token in tokens):
        return True
    return len(tokens) <= 3


def doctor_bio_node(state: ClinicChatState) -> dict:
    agent = _get_rag_agent()
    result = agent.answer(query=_resolved_query(state), top_k=5, system_prompt=_system_prompt(state))
    if _rag_result_is_uncertain(result):
        return _clarification_result(result)
    return {
        "response": _reply(result["response"]),
        "chunks": serialize_chunks(result.get("chunks", [])),
        "data": {},
    }


def availability_node(state: ClinicChatState) -> dict:
    conversation = state.get("conversation", {"mode": None, "booking": {}})
    doctor_id = state.get("doctor_id") or (conversation.get("booking") or {}).get("doctor_id")
    appointment_date = (
        state.get("appointment_date")
        or (conversation.get("booking") or {}).get("date")
        or parse_date(state["message"])
    )
    appointment_time = state.get("appointment_time") or (conversation.get("booking") or {}).get("time")

    if not appointment_date and not doctor_id and _looks_like_doctor_directory_request(state["message"]):
        doctors = list_doctors()
        if not doctors:
            return {
                "response": _reply("I could not find any doctors in the clinic database right now."),
                "data": {"doctors": []},
                "conversation": conversation,
            }

        lines = []
        for doctor in doctors:
            specialization = f" ({doctor['specialization']})" if doctor.get("specialization") else ""
            lines.append(f"- Dr. {doctor['doctor_name'].removeprefix('Dr. ').strip()}{specialization}")
        return {
            "response": _reply(
                "Doctors available at Nishant Care:\n" + "\n".join(lines),
                next_step="Share a date if you want available appointment slots.",
            ),
            "data": {"doctors": doctors},
            "conversation": conversation,
        }

    # Recall a doctor named earlier in this thread so "is he free tomorrow?" works
    # after the patient already picked a doctor on a previous turn.
    if not doctor_id:
        remembered = conversation.get("last_doctor_name")
        if not remembered:
            for item in reversed(state.get("history") or []):
                if item.get("role") == "user" and (item.get("content") or "").strip():
                    remembered = item["content"].strip()
                    break
        if remembered:
            matched = _resolve_doctor_from_text(remembered)
            if matched:
                doctor_id = matched["doctor_id"]
                conversation["last_doctor_name"] = matched["doctor_name"]

    if not appointment_date:
        return {
            "response": _reply(FIELD_QUESTIONS["date"]),
            "data": {"required": ["appointment_date"]},
            "conversation": conversation,
        }

    if not doctor_id:
        doctors = list_doctor_availability(appointment_date)
        available_doctors = [doctor for doctor in doctors if doctor["available"]]
        if not available_doctors:
            return {
                "response": _reply(f"No doctors have available slots on {appointment_date}.", next_step="Choose another date."),
                "data": {"date": str(appointment_date), "doctors": doctors, "memories": state.get("long_term_memories", [])},
                "conversation": conversation,
            }

        lines = []
        for doctor in available_doctors:
            times = ", ".join(str(slot["time"])[:5] for slot in doctor["available_slots"][:8])
            more = "..." if doctor["slot_count"] > 8 else ""
            specialization = f" ({doctor['specialization']})" if doctor.get("specialization") else ""
            lines.append(f"- Dr. {doctor['doctor_name'].removeprefix('Dr. ').strip()}{specialization}: {times}{more}")

        conversation["last_availability"] = {"date": str(appointment_date), "doctors": doctors}
        return {
            "response": _reply(f"Available doctors on {appointment_date}:\n" + "\n".join(lines), next_step="Tell me the doctor and time you prefer."),
            "data": {"date": str(appointment_date), "doctors": doctors, "memories": state.get("long_term_memories", [])},
            "conversation": conversation,
        }

    slots = check_slots(doctor_id, appointment_date)
    if not slots:
        return {
            "response": _reply("I could not find a schedule for that doctor.", next_step="Choose another doctor."),
            "data": {"doctor_id": doctor_id},
            "conversation": conversation,
        }

    if appointment_time:
        reason = explain_slot(doctor_id, appointment_date, appointment_time)
        if reason is None:
            return {
                "response": _reply("That slot is available.", next_step="Send the patient name."),
                "data": {
                    "available": True,
                    "doctor_id": doctor_id,
                    "date": str(appointment_date),
                    "time": str(appointment_time),
                    "next_step": "booking_chat",
                },
                "conversation": conversation,
            }
        return {
            "response": _reply("That slot is not available.", next_step="Choose another available time."),
            "data": {"available": False, "reason": reason, "slots": slots},
            "conversation": conversation,
        }

    return {
        "response": _reply("Here are the available appointment slots.", next_step="Tell me which time you prefer."),
        "data": {
            "available": any(slot["available"] for slot in slots),
            "doctor_id": doctor_id,
            "date": str(appointment_date),
            "slots": slots,
        },
        "conversation": conversation,
    }


def _format_available_times(slots: list[dict[str, Any]]) -> str:
    available = [str(slot["time"])[:5] for slot in slots if slot.get("available")]
    if not available:
        return "No slots are available for that date."
    return "Available times: " + ", ".join(available[:12])



def _plain_answer_for_field(text: str, field: str) -> Any | None:
    cleaned = text.strip().strip(" .,;:-")
    lowered = cleaned.lower()
    if not cleaned:
        return None
    if field == "patient_name":
        if any(char.isdigit() for char in cleaned) or "@" in cleaned:
            return None
        words = cleaned.split()
        if 1 <= len(words) <= 5 and all(len(word) >= 2 for word in words):
            return cleaned.title()
    if field == "age" and cleaned.isdigit():
        age = int(cleaned)
        if 0 <= age <= 130:
            return age
    if field == "sex" and lowered in {"male", "female", "other"}:
        return lowered.title()
    return None


def _invalid_field_feedback(text: str, field: str) -> str | None:
    cleaned = text.strip()
    lowered = cleaned.lower()
    if not cleaned:
        return None

    if field == "email":
        return "Please enter a valid email address, for example ram@example.com."
    if field == "age":
        return "Please enter a valid age as a number between 0 and 130."
    if field == "sex":
        return "Please choose one of these options: Male, Female, or Other."
    if field == "phone":
        return "Please enter a valid phone number with at least 7 digits."
    if field == "date":
        if re.search(r"\d|today|tomorrow|tommorrow|tommrow|tmrw|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec", lowered):
            return "Please enter a valid appointment date, for example 2026-10-05, or choose a date from the calendar."
    if field == "time":
        if re.search(r"\d|am|pm|morning|afternoon|evening", lowered):
            return "Please enter a valid appointment time, for example 10:30 AM."
    if field == "patient_name":
        if any(char.isdigit() for char in cleaned) or "@" in cleaned or len(cleaned) < 2:
            return "Please enter a valid patient name using letters, for example Ramchandra Khada."
    return None


def _confirmation_answer(text: str) -> bool | None:
    cleaned = text.strip().lower()
    cleaned = re.sub(r"[.!?:,;]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned in {"yes", "y", "yeah", "yep", "confirm", "confirmed", "correct", "that's right", "that is right"}:
        return True
    if cleaned in {"no", "n", "nope", "cancel", "stop", "not now", "do not confirm"}:
        return False
    return None


def _format_booking_confirmation_question(booking: dict[str, Any]) -> str:
    date_text = str(booking["date"])
    time_value = datetime.strptime(str(booking["time"])[:5], "%H:%M").time()
    time_text = time_value.strftime("%I:%M %p").lstrip("0")
    patient_name = booking.get("patient_name", "the patient")
    return f"Do you want to confirm the appointment for {patient_name} on {date_text} at {time_text}?"


def _booking_doctor_question() -> str:
    doctors = list_doctors()
    names = ", ".join(doctor["doctor_name"] for doctor in doctors[:8])
    question = "Which doctor would you like to book with? You can type the doctor's name"
    if names:
        question += f". Available doctors: {names}"
    question += "."
    return question


def _booking_past_slot_response(booking: dict[str, Any], conversation: dict[str, Any]) -> dict | None:
    if not booking.get("date"):
        return None

    try:
        slot_date = datetime.strptime(str(booking["date"]), "%Y-%m-%d").date()
    except ValueError:
        return None

    today = datetime.now(settings.clinic_tzinfo).date()
    if slot_date < today:
        booking.pop("date", None)
        booking.pop("time", None)
        conversation["booking"] = booking
        conversation["required"] = ["date"]
        return {
            "response": _reply(
                "That date is in the past. Please choose today or a future date.",
                next_step="Select a date from the calendar or type YYYY-MM-DD.",
            ),
            "data": {"booking": booking, "required": ["date"]},
            "conversation": conversation,
        }

    if not booking.get("time"):
        return None

    try:
        slot_time = datetime.strptime(str(booking["time"])[:5], "%H:%M").time()
    except ValueError:
        return None

    slot_moment = datetime.combine(slot_date, slot_time, tzinfo=settings.clinic_tzinfo)
    if slot_moment <= datetime.now(settings.clinic_tzinfo):
        booking.pop("time", None)
        conversation["booking"] = booking
        conversation["required"] = ["time"]
        return {
            "response": _reply(
                "That time has already passed. Please choose a later slot.",
                next_step="Pick one of the available times.",
            ),
            "data": {"booking": booking, "required": ["time"]},
            "conversation": conversation,
        }

    return None


def booking_node(state: ClinicChatState) -> dict:
    conversation = state.get("conversation", {"mode": None, "booking": {}})
    booking = conversation.get("booking", {})
    expected_field = (conversation.get("required") or missing_fields(booking) or [None])[0]
    booking = extract_booking_fields(state["message"], booking)

    if expected_field and not booking.get(expected_field):
        plain_value = _plain_answer_for_field(state["message"], expected_field)
        if plain_value is not None:
            booking[expected_field] = plain_value
        elif expected_field in {"date", "time"}:
            parsed_value = parse_date(state["message"]) if expected_field == "date" else parse_time(state["message"])
            if parsed_value is None:
                feedback = _invalid_field_feedback(state["message"], expected_field)
                if feedback:
                    conversation["mode"] = "booking"
                    conversation["booking"] = booking
                    conversation["required"] = [expected_field]
                    return {
                        "response": _reply(feedback, next_step=FIELD_QUESTIONS[expected_field]),
                        "data": {"booking": booking, "required": [expected_field]},
                        "conversation": conversation,
                    }
        else:
            feedback = _invalid_field_feedback(state["message"], expected_field)
            if feedback:
                conversation["mode"] = "booking"
                conversation["booking"] = booking
                conversation["required"] = [expected_field]
                return {
                    "response": _reply(feedback, next_step=FIELD_QUESTIONS[expected_field]),
                    "data": {"booking": booking, "required": [expected_field]},
                    "conversation": conversation,
                }

    last_availability = conversation.get("last_availability") or {}
    candidates = last_availability.get("doctors") if isinstance(last_availability, dict) else None
    if not booking.get("doctor_id"):
        # Search this turn first, then fall back to a doctor named in an earlier turn
        # so "book him at 10" keeps working after the patient already chose.
        sources = [state["message"]]
        if not conversation.get("last_doctor_name"):
            previous = next(
                (
                    item.get("content", "").strip()
                    for item in reversed(state.get("history") or [])
                    if item.get("role") == "user" and (item.get("content") or "").strip()
                ),
                "",
            )
            if previous:
                sources.append(previous)
        for source in sources:
            matched_doctor = _resolve_doctor_from_text(source, candidates)
            if matched_doctor:
                booking["doctor_id"] = matched_doctor["doctor_id"]
                booking["doctor_name"] = matched_doctor["doctor_name"]
                conversation["last_doctor_name"] = matched_doctor["doctor_name"]
                break

    if state.get("doctor_id") and not booking.get("doctor_id"):
        booking["doctor_id"] = state["doctor_id"]
    if state.get("appointment_date") and not booking.get("date"):
        booking["date"] = str(state["appointment_date"])
    if not booking.get("date") and isinstance(last_availability, dict) and last_availability.get("date"):
        booking["date"] = last_availability["date"]
    if state.get("appointment_time") and not booking.get("time"):
        booking["time"] = str(state["appointment_time"])[:5]

    conversation["mode"] = "booking"
    conversation["booking"] = booking

    missing = missing_fields(booking)
    conversation["required"] = missing[:1]

    past_slot_response = _booking_past_slot_response(booking, conversation)
    if past_slot_response is not None:
        return past_slot_response
    
    if "doctor_id" not in missing and "date" not in missing:
        try:
            slot_date = datetime.strptime(booking["date"], "%Y-%m-%d").date()
        except ValueError:
            booking.pop("date", None)
            conversation["booking"] = booking
            conversation["required"] = ["date"]
            return {
                "response": _reply(FIELD_QUESTIONS["date"], next_step="For example, 2026-10-05 or tomorrow."),
                "data": {"booking": booking, "required": ["date"]},
                "conversation": conversation,
            }

        slots = check_slots(int(booking["doctor_id"]), slot_date)
        if not slots:
            booking.pop("doctor_id", None)
            booking.pop("doctor_name", None)
            conversation["booking"] = booking
            conversation["required"] = ["doctor_id"]
            return {
                "response": _reply(
                    "I could not find a schedule for that doctor.",
                    next_step=_booking_doctor_question(),
                ),
                "data": {"booking": booking, "required": ["doctor_id"]},
                "conversation": conversation,
            }
        if "time" in missing:
            return {
                "response": _reply(_format_available_times(slots), next_step="Tell me which time to book."),
                "data": {"booking": booking, "slots": slots, "required": ["time"]},
                "conversation": conversation,
            }

    if missing:
        next_field = missing[0]
        if next_field == "doctor_id":
            question = _booking_doctor_question()
        else:
            question = FIELD_QUESTIONS[next_field]
        return {
            "response": _reply(question),
            "data": {"booking": booking, "required": [next_field], "memories": state.get("long_term_memories", [])},
            "conversation": conversation,
        }

    if conversation.get("awaiting_confirmation"):
        confirmation = _confirmation_answer(state["message"])
        if confirmation is False:
            return {
                "response": _reply("Okay, I have not booked the appointment."),
                "data": {"booking": booking, "confirmed": False},
                "conversation": {"mode": None, "booking": {}},
            }
        if confirmation is not True:
            return {
                "response": _reply(_format_booking_confirmation_question(booking), next_step="Reply yes to confirm or no to cancel."),
                "data": {"booking": booking, "required": ["confirmation"], "awaiting_confirmation": True},
                "conversation": conversation,
            }
        conversation["awaiting_confirmation"] = False
    else:
        conversation["awaiting_confirmation"] = True
        conversation["required"] = ["confirmation"]
        return {
            "response": _reply(_format_booking_confirmation_question(booking), next_step="Reply yes to confirm or no to cancel."),
            "data": {"booking": booking, "required": ["confirmation"], "awaiting_confirmation": True},
            "conversation": conversation,
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
            "response": _reply("Some appointment details look invalid.", next_step="Send the date as YYYY-MM-DD and time like 10:30 AM."),
            "data": {"booking": booking, "error": str(exc)},
            "conversation": conversation,
        }

    result = book_appointment(appointment)
    if result["status"] != "success":
        reason = result.get("reason", "unavailable")
        if reason in {"slot_booked", "during_break", "after_working_hours", "before_working_hours", "doctor_on_leave", "not_working_day"}:
            slots = check_slots(appointment.doctor_id, appointment.date)
            booking.pop("time", None)
            conversation["booking"] = booking
            return {
                "response": _reply(f"That time is not available ({reason}). " + _format_available_times(slots), next_step="Tell me which time to book."),
                "data": {"booking": booking, "reason": reason, "slots": slots, "required": ["time"]},
                "conversation": conversation,
            }
        return {
            "response": _reply("Sorry, I could not book that appointment.", next_step="Try another slot."),
            "data": result,
            "conversation": conversation,
        }

    appt = result["appointment"]
    return {
        "response": _reply(
            f"Your appointment is confirmed for {appt['date']} at {appt['time']}. "
            f"The confirmation email status is {appt.get('email_status', 'pending')}."
        ),
        "data": result,
        "conversation": {"mode": None, "booking": {}},
    }


def faq_node(state: ClinicChatState) -> dict:
    """Answer from the curated FAQ; fall through to document RAG on a weak match."""
    # Long-term memories are withheld here on purpose: FAQ answers are approved
    # clinic facts and must not be steerable by stored text.
    system_prompt = _system_prompt(state, include_memories=False)
    result = _get_faq_agent().answer(_resolved_query(state), system_prompt=system_prompt)

    if result.get("matched"):
        faq = result.get("faq") or {}
        return {
            "response": _reply(result["response"]),
            "chunks": [],
            "data": {
                "faq_id": faq.get("id"),
                "category": faq.get("category"),
                "matched_question": faq.get("question"),
                "score": faq.get("score"),
            },
        }

# No confident FAQ hit: answer from the clinic documents instead.
    rag_result = _get_rag_agent().answer(
        query=_resolved_query(state), top_k=5, system_prompt=_system_prompt(state)
    )
    if _rag_result_is_uncertain(rag_result):
        return _clarification_result(rag_result)
    return {
        "response": _reply(rag_result["response"]),
        "chunks": serialize_chunks(rag_result.get("chunks", [])),
        "data": {"faq_fallback": "rag"},
    }


def medical_web_node(state: ClinicChatState) -> dict:
    return _get_medical_agent().answer(_resolved_query(state), system_prompt=_system_prompt(state))


def out_of_scope_node(state: ClinicChatState) -> dict:
    return {
        "response": _reply(
            "I can help with healthcare, clinic information, doctor availability, and appointment booking only.",
            next_step="Ask a clinic or health-related question.",
        ),
        "data": {"scope": "out_of_scope"},
    }


def fallback_node(state: ClinicChatState) -> dict:
    if _is_assistant_identity_question(state["message"]):
        return {
            "response": _reply(
                "I am the clinic assistant. I can help with doctor information, availability, and appointment booking.",
                next_step="Ask about a doctor, check availability, or book an appointment.",
            ),
            "data": {"assistant_identity": True},
        }

    # A greeting mid-thread is not a dead end: acknowledge it and point back at
    # what the patient was already doing instead of restarting the script.
    if (state.get("history") or []) and state["message"].strip().lower().strip("!. ") in {
        "hi", "hello", "hey", "namaste", "good morning", "good afternoon", "good evening",
    }:
        return {
            "response": _reply(
                "Namaste! I'm still here if you want to carry on.",
                next_step="Ask about a doctor, check availability, or book an appointment.",
            ),
            "data": {"resumed": True},
        }
    return {
        "response": _reply("I can help with doctor information, availability, and appointment booking.", next_step="Ask about a doctor, check availability, or book an appointment."),
        "data": {},
    }


def choose_node(state: ClinicChatState) -> str:
    return state.get("intent", "fallback")
