import re
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import settings

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?\d[\d\s-]{6,}\d)")
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
DOCTOR_ID_RE = re.compile(r"\bdoctor(?:_id| id)?\s*(?:is|=|:)?\s*(\d+)\b", re.I)
AGE_RE = re.compile(r"\b(?:age(?: is)?|i am|i'm)\s*(\d{1,3})\b", re.I)
SEX_RE = re.compile(r"\b(male|female|other)\b", re.I)

FIELD_QUESTIONS = {
    "doctor_id": "Which doctor would you like to book with? Please provide the doctor ID.",
    "date": "What date would you like for the appointment? Please use YYYY-MM-DD.",
    "time": "What time would you prefer? For example, 10:30 AM.",
    "patient_name": "What is the patient name?",
    "age": "What is the patient's age?",
    "sex": "What is the patient's sex?",
    "email": "What email should I send the confirmation to?",
    "phone": "What phone number should the clinic use?",
}

REQUIRED_FIELDS = ["doctor_id", "date", "time", "patient_name", "age", "sex", "email", "phone"]

MemoryKey = Literal[
    "preferred_doctor",
    "preferred_specialty",
    "preferred_time",
    "language",
    "contact_preference",
    "books_for_family",
]


class ExtractedMemory(BaseModel):
    key: MemoryKey
    value: str = Field(max_length=200)


class ExtractionResult(BaseModel):
    memories: list[ExtractedMemory] = []


def parse_date(text: str):
    lowered = text.lower()
    today = datetime.now(settings.clinic_tzinfo).date()
    if "tomorrow" in lowered:
        return today + timedelta(days=1)
    if "today" in lowered:
        return today
    match = DATE_RE.search(text)
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    return None


def parse_time(text: str):
    candidates = []
    for match in TIME_RE.finditer(text):
        has_minutes = match.group(2) is not None
        has_suffix = match.group(3) is not None
        if not has_minutes and not has_suffix:
            continue
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        suffix = (match.group(3) or "").lower()
        if suffix == "pm" and hour != 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            priority = 0 if has_suffix else 1
            candidates.append((priority, match.start(), f"{hour:02d}:{minute:02d}"))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def extract_booking_fields(text: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    fields = dict(existing or {})

    doctor_match = DOCTOR_ID_RE.search(text)
    if doctor_match:
        fields["doctor_id"] = int(doctor_match.group(1))

    parsed_date = parse_date(text)
    if parsed_date:
        fields["date"] = str(parsed_date)

    parsed_time = parse_time(text)
    if parsed_time:
        fields["time"] = parsed_time

    email_match = EMAIL_RE.search(text)
    if email_match:
        fields["email"] = email_match.group(0).lower()

    phone_source = DATE_RE.sub(" ", text)
    phone_source = TIME_RE.sub(" ", phone_source)
    phone_match = PHONE_RE.search(phone_source)
    if phone_match:
        phone_digits = re.sub(r"\D", "", phone_match.group(0))
        if len(phone_digits) >= 7:
            fields["phone"] = re.sub(r"\s+", "", phone_match.group(0))

    age_match = AGE_RE.search(text)
    if age_match:
        fields["age"] = int(age_match.group(1))

    sex_match = SEX_RE.search(text)
    if sex_match:
        fields["sex"] = sex_match.group(1).title()

    lowered = text.lower().strip()
    if "patient_name" not in fields and any(prefix in lowered for prefix in ("my name is", "patient name is", "name is")):
        name = re.sub(r"^(my name is|patient name is|name is)\s+", "", text.strip(), flags=re.I)
        name = EMAIL_RE.sub("", name)
        name = PHONE_RE.sub("", name).strip(" .,;:-")
        if len(name.split()) <= 5 and len(name) >= 2:
            fields["patient_name"] = name.title()

    return fields


def missing_fields(fields: dict[str, Any]) -> list[str]:
    return [field for field in REQUIRED_FIELDS if not fields.get(field)]
