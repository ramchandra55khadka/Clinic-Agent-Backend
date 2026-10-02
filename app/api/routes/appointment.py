from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app import repositories
from app.api.deps import get_current_user, require_staff
from app.db.session import get_db
from app.models.user_account import UserAccount
from app.schemas.appointment import AppointmentCreate, AppointmentOut, AppointmentUpdate
from app.schemas.availability import AvailabilityRequest, AvailabilityResponse, SlotOut
from app.schemas.doctor import DoctorScheduleCreate, DoctorScheduleOut, DoctorScheduleUpdate
from app.services import appointments as appointment_service
from app.services.appointments import BookingError
from app.services.availability import explain_unavailability, get_available_slots
from app.services.email_scheduler import send_confirmation_for_appointment_id

router = APIRouter(tags=["appointments"])

# --------------------------------------------------------------------------- #
# Doctor schedules
#
# A doctor's schedule *is* their availability: working hours, lunch break, time
# off and slot length. It is maintained by clinic staff or an admin — patients
# may read it (they need doctor names and hours) but never change it.
# --------------------------------------------------------------------------- #


def _schedule_out(schedule) -> dict:
    """Flattens a schedule + its normalized doctor/profile into the API shape.

    ``id``/``doctor_id`` are the doctor's id (the bookable identity); the schedule
    row's own primary key is exposed as ``schedule_id``.
    """
    doctor = schedule.doctor
    profile = doctor.profile if doctor else None
    return {
        "id": schedule.doctor_id,
        "doctor_id": schedule.doctor_id,
        "schedule_id": schedule.id,
        "doctor_name": profile.full_name if profile else "",
        "specialization": doctor.specialization if doctor else None,
        "photo_url": profile.photo_url if profile else None,
        "start_time": schedule.start_time,
        "end_time": schedule.end_time,
        "break_start": schedule.break_start,
        "break_end": schedule.break_end,
        "leave_date": schedule.leave_date,
        "slot_duration": schedule.slot_duration,
        "license_number": doctor.license_number if doctor else None,
        "qualification": doctor.qualification if doctor else None,
        "experience_years": doctor.experience_years if doctor else None,
        "bio": doctor.bio if doctor else None,
        "consultation_fee": doctor.consultation_fee if doctor else None,
        "consultation_duration": doctor.consultation_duration if doctor else None,
        "is_verified": doctor.is_verified if doctor else False,
    }


@router.post("/doctor-schedule/", response_model=DoctorScheduleOut)
def create_schedule(schedule: DoctorScheduleCreate, db: Session = Depends(get_db), _staff=Depends(require_staff)):
    return _schedule_out(repositories.create_doctor_schedule(db, schedule))


@router.get("/doctor-schedule/{doctor_id}", response_model=DoctorScheduleOut)
def get_schedule(doctor_id: int, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    schedule = repositories.get_doctor_schedule(db, doctor_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    return _schedule_out(schedule)


@router.get("/doctor-schedule/", response_model=list[DoctorScheduleOut])
def list_doctor_schedules(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    return [_schedule_out(schedule) for schedule in repositories.get_all_doctor_schedules(db)]


@router.put("/doctor-schedule/{doctor_id}", response_model=DoctorScheduleOut)
def update_schedule(doctor_id: int, schedule: DoctorScheduleUpdate, db: Session = Depends(get_db), _staff=Depends(require_staff)):
    updated = repositories.update_doctor_schedule(db, doctor_id, schedule)
    if not updated:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    return _schedule_out(updated)


@router.delete("/doctor-schedule/{doctor_id}")
def delete_schedule(doctor_id: int, db: Session = Depends(get_db), _staff=Depends(require_staff)):
    success = repositories.delete_doctor_schedule(db, doctor_id)
    if not success:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    return {"message": "Doctor schedule deleted successfully"}


@router.post("/appointments/", response_model=AppointmentOut)
def create_appointment(
    appointment: AppointmentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _user: UserAccount = Depends(get_current_user),
):
    try:
        saved = appointment_service.book_appointment(db, appointment)
    except BookingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    # SMTP must never block or fail the response: send the confirmation afterwards.
    background_tasks.add_task(send_confirmation_for_appointment_id, saved.id)
    return saved


# --------------------------------------------------------------------------- #
# Self-service: a patient's own appointments
#
# Declared before `/appointments/{doctor_id}` so "me" is not parsed as an id.
# Ownership is the email the appointment was booked with.
# --------------------------------------------------------------------------- #

def _owned_appointment(db: Session, appointment_id: int, user: UserAccount):
    """The caller's appointment, or 404 — never revealing someone else's booking."""
    appointment = repositories.get_appointment(db, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")

    owns_it = (appointment.email or "").strip().lower() == (user.email or "").strip().lower()
    if not owns_it:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appointment


@router.get("/appointments/me", response_model=list[AppointmentOut])
def list_my_appointments(
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    """Every appointment booked with the signed-in patient's email."""
    return repositories.get_appointments_by_email(db, current_user.email)


@router.get("/appointments/me/{appointment_id}", response_model=AppointmentOut)
def get_my_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    return _owned_appointment(db, appointment_id, current_user)


@router.put("/appointments/me/{appointment_id}", response_model=AppointmentOut)
def update_my_appointment(
    appointment_id: int,
    payload: AppointmentUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    """Edit patient details or reschedule. A moved slot is re-checked for
    availability and the confirmation email is sent again."""
    appointment = _owned_appointment(db, appointment_id, current_user)

    if appointment.status == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="This appointment was cancelled and can no longer be changed.",
        )

    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    rescheduled = "date" in changes or "time" in changes

    try:
        updated = appointment_service.update_owned_appointment(db, appointment, payload)
    except BookingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    repositories.log_audit(
        db,
        action="appointment.updated",
        actor=current_user,
        entity="appointment",
        entity_id=updated.id,
        detail="rescheduled" if rescheduled else "details updated",
    )

    if rescheduled:
        background_tasks.add_task(send_confirmation_for_appointment_id, updated.id)

    return updated


@router.post("/appointments/me/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_my_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    """Cancels the appointment, which frees the slot for other patients."""
    appointment = _owned_appointment(db, appointment_id, current_user)
    updated = appointment_service.cancel_owned_appointment(db, appointment)

    repositories.log_audit(
        db,
        action="appointment.cancelled",
        actor=current_user,
        entity="appointment",
        entity_id=updated.id,
    )
    return updated


@router.get("/appointments/{doctor_id}", response_model=list[AppointmentOut])
def list_appointments(doctor_id: int, db: Session = Depends(get_db), _staff=Depends(require_staff)):
    """Clinic-wide view for staff: every appointment for one doctor.

    Staff (front desk) need the day list to run the clinic; patients see only
    their own bookings through ``/appointments/me``.
    """
    return repositories.get_appointments_by_doctor(db, doctor_id)


@router.post("/availability/", response_model=AvailabilityResponse)
def check_doctor_availability(
    request: AvailabilityRequest,
    db: Session = Depends(get_db),
    _user: UserAccount = Depends(get_current_user),
):
    slots = get_available_slots(db, request.doctor_id, request.date)
    if request.time is None:
        return AvailabilityResponse(
            doctor_id=request.doctor_id,
            date=request.date,
            available=any(slot["available"] for slot in slots),
            slots=[SlotOut(**slot) for slot in slots],
        )

    reason = explain_unavailability(db, request.doctor_id, request.date, request.time)
    return AvailabilityResponse(
        doctor_id=request.doctor_id,
        date=request.date,
        available=reason is None,
        reason=reason,
        slots=[SlotOut(**slot) for slot in slots],
    )


@router.get("/availability/{doctor_id}/{appointment_date}", response_model=AvailabilityResponse)
def list_available_slots(
    doctor_id: int,
    appointment_date: date,
    exclude_appointment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserAccount = Depends(get_current_user),
):
    """Slots for one day.

    ``exclude_appointment_id`` lets a patient see their own slot as free while
    rescheduling; it is ignored unless that appointment belongs to the caller.
    """
    excluded = exclude_appointment_id
    if excluded is not None:
        owned = repositories.get_appointment(db, excluded)
        if owned is None or (owned.email or "").strip().lower() != (current_user.email or "").strip().lower():
            excluded = None

    slots = get_available_slots(db, doctor_id, appointment_date, exclude_appointment_id=excluded)
    if not slots:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    return AvailabilityResponse(
        doctor_id=doctor_id,
        date=appointment_date,
        available=any(slot["available"] for slot in slots),
        slots=[SlotOut(**slot) for slot in slots],
    )
