"""Doctor and working-hours repositories."""

from sqlalchemy.orm import Session

from app.core.days import days_to_column
from app.models.doctor import Doctor
from app.models.doctor_education import DoctorEducation
from app.models.doctor_schedule import DoctorSchedule
from app.models.user_profile import UserProfile
from app.schemas.doctor import DoctorScheduleCreate, DoctorScheduleUpdate


def create_doctor_schedule(db: Session, schedule: DoctorScheduleCreate):
    """Creates the normalized doctor (a ``user_profile`` + ``doctor``) and its hours."""
    data = schedule.model_dump()

    profile = UserProfile(
        first_name=data.get("first_name", ""),
        last_name=data.get("last_name"),
        email=data.get("email"),
        phone=data.get("phone"),
        date_of_birth=data.get("date_of_birth"),
        gender=data.get("gender"),
        address=data.get("address"),
        photo_url=data.get("photo_url"),
    )
    doctor = Doctor(
        profile=profile,
        specialization=data.get("specialization"),
        license_number=data.get("license_number"),
        qualification=data.get("qualification"),
        experience_years=data.get("experience_years"),
        bio=data.get("bio"),
        consultation_fee=data.get("consultation_fee"),
        consultation_duration=data.get("consultation_duration") or data.get("slot_duration") or 30,
        is_verified=bool(data.get("is_verified")),
    )
    db.add(doctor)
    db.flush()
    for education in data.get("educations", []):
        db.add(DoctorEducation(doctor_id=doctor.id, **education))

    db_schedule = DoctorSchedule(
        doctor_id=doctor.id,
        start_time=data["start_time"],
        end_time=data["end_time"],
        break_start=data.get("break_start"),
        break_end=data.get("break_end"),
        leave_date=data.get("leave_date"),
        slot_duration=data.get("slot_duration") or doctor.consultation_duration or 30,
        working_days=days_to_column(data.get("days")),
    )
    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)
    return db_schedule


def get_doctor_schedule(db: Session, doctor_id: int):
    """The (single) working-hours row of a doctor, addressed by the doctor id."""
    return db.query(DoctorSchedule).filter(DoctorSchedule.doctor_id == doctor_id).first()


def get_all_doctor_schedules(db: Session):
    return db.query(DoctorSchedule).all()


def get_doctor(db: Session, doctor_id: int):
    return db.query(Doctor).filter(Doctor.id == doctor_id).first()


#: Fields that live on the schedule row itself.
_SCHEDULE_FIELDS = {"start_time", "end_time", "break_start", "break_end", "leave_date", "slot_duration"}
#: Fields that live on the normalized ``doctor`` row.
_DOCTOR_FIELDS = {
    "specialization",
    "license_number",
    "qualification",
    "experience_years",
    "bio",
    "consultation_fee",
    "consultation_duration",
    "is_verified",
}
#: Fields that live on the ``user_profile`` row.
_PROFILE_FIELDS = {
    "first_name",
    "last_name",
    "email",
    "phone",
    "date_of_birth",
    "gender",
    "address",
    "photo_url",
}


def _replace_doctor_educations(db: Session, doctor: Doctor, educations: list[dict]):
    for education in list(doctor.educations):
        db.delete(education)
    db.flush()
    for education in educations:
        db.add(DoctorEducation(doctor_id=doctor.id, **education))


def update_doctor_schedule(db: Session, doctor_id: int, schedule: DoctorScheduleUpdate):
    db_schedule = get_doctor_schedule(db, doctor_id)
    if not db_schedule:
        return None

    for key, value in schedule.model_dump(exclude_unset=True).items():
        if key == "days":
            db_schedule.working_days = days_to_column(value)
        elif key in _SCHEDULE_FIELDS:
            setattr(db_schedule, key, value)
        elif key == "educations" and db_schedule.doctor is not None:
            _replace_doctor_educations(db, db_schedule.doctor, value or [])
        elif key in _PROFILE_FIELDS and db_schedule.doctor.profile is not None:
            setattr(db_schedule.doctor.profile, key, value)
        elif key in _DOCTOR_FIELDS and db_schedule.doctor is not None:
            setattr(db_schedule.doctor, key, value)

    db.commit()
    db.refresh(db_schedule)
    return db_schedule


def delete_doctor_schedule(db: Session, doctor_id: int):
    db_schedule = get_doctor_schedule(db, doctor_id)
    if not db_schedule:
        return False

    doctor = db_schedule.doctor
    profile = doctor.profile if doctor else None

    if doctor is not None:
        # Deleting the doctor cascades to its schedules and educations.
        db.delete(doctor)
    if profile is not None:
        # ``UserProfile`` no longer back-references the doctor, so it is removed
        # explicitly rather than through a reverse-relationship cascade.
        db.delete(profile)
    if doctor is None and profile is None:  # pragma: no cover - defensive
        db.delete(db_schedule)

    db.commit()
    return True
