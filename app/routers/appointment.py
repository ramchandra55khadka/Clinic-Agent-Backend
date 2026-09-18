from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import crud
from app.database.database import get_db
from app.database.models import UserAccount
from app.database.schema import (
    AppointmentCreate,
    AppointmentOut,
    AvailabilityRequest,
    AvailabilityResponse,
    DoctorScheduleCreate,
    DoctorScheduleOut,
    DoctorScheduleUpdate,
    SlotOut,
)
from app.dependencies.auth import get_current_user, require_admin
from app.services import appointments as appointment_service
from app.services.appointments import BookingError
from app.services.availability import explain_unavailability, get_available_slots
from app.services.email_scheduler import send_confirmation_for_appointment_id

router = APIRouter(tags=["appointments"])


@router.post("/doctor-schedule/", response_model=DoctorScheduleOut)
def create_schedule(schedule: DoctorScheduleCreate, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    return crud.create_doctor_schedule(db, schedule)


@router.get("/doctor-schedule/{doctor_id}", response_model=DoctorScheduleOut)
def get_schedule(doctor_id: int, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    schedule = crud.get_doctor_schedule(db, doctor_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    return schedule


@router.get("/doctor-schedule/", response_model=list[DoctorScheduleOut])
def list_doctor_schedules(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    return crud.get_all_doctor_schedules(db)


@router.put("/doctor-schedule/{doctor_id}", response_model=DoctorScheduleOut)
def update_schedule(doctor_id: int, schedule: DoctorScheduleUpdate, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    updated = crud.update_doctor_schedule(db, doctor_id, schedule)
    if not updated:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    return updated


@router.delete("/doctor-schedule/{doctor_id}")
def delete_schedule(doctor_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    success = crud.delete_doctor_schedule(db, doctor_id)
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


@router.get("/appointments/{doctor_id}", response_model=list[AppointmentOut])
def list_appointments(doctor_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    return crud.get_appointments_by_doctor(db, doctor_id)


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
    db: Session = Depends(get_db),
    _user: UserAccount = Depends(get_current_user),
):
    slots = get_available_slots(db, doctor_id, appointment_date)
    if not slots:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    return AvailabilityResponse(
        doctor_id=doctor_id,
        date=appointment_date,
        available=any(slot["available"] for slot in slots),
        slots=[SlotOut(**slot) for slot in slots],
    )
