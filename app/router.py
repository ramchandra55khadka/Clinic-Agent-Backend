from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import crud
from app.schemas import AppointmentCreate,AppointmentOut,DoctorScheduleCreate,DoctorScheduleOut
from app.database.database import get_db

router=APIRouter()


# -------------------- Doctor Schedule --------------------

@router.post("/doctor-schedule/", response_model=DoctorScheduleOut)
def create_schedule(schedule: DoctorScheduleCreate, db: Session = Depends(get_db)):
    return crud.create_doctor_schedule(db, schedule)


@router.get("/doctor-schedule/{doctor_id}", response_model=DoctorScheduleOut)
def get_schedule(doctor_id: int, db: Session = Depends(get_db)):
    schedule = crud.get_doctor_schedule(db, doctor_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    return schedule

#Get all doctor schedule
@router.get("/doctor-schedule/", response_model=list[DoctorScheduleOut])
def list_doctor_schedules(db: Session = Depends(get_db)):
    schedules = crud.get_all_doctor_schedules(db)
    return schedules

@router.put("/doctor-schedule/{doctor_id}", response_model=DoctorScheduleOut)
def update_schedule(doctor_id: int, schedule: DoctorScheduleCreate, db: Session = Depends(get_db)):
    updated = crud.update_doctor_schedule(db, doctor_id, schedule)
    if not updated:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    return updated


@router.delete("/doctor-schedule/{doctor_id}")
def delete_schedule(doctor_id: int, db: Session = Depends(get_db)):
    success = crud.delete_doctor_schedule(db, doctor_id)
    if not success:
        raise HTTPException(status_code=404, detail="Doctor schedule not found")
    return {"message": "Doctor schedule deleted successfully"}


# -------------------- Appointments --------------------

@router.post("/appointments/", response_model=AppointmentOut)
def create_appointment(appointment: AppointmentCreate, db: Session = Depends(get_db)):
    available = crud.check_availability(
        db, appointment.doctor_id, appointment.date, appointment.time
    )
    if not available:
        raise HTTPException(
            status_code=400,
            detail="Doctor is not available at this time or slot already booked."
        )
    return crud.create_appointment(db, appointment)


@router.get("/appointments/{doctor_id}", response_model=List[AppointmentOut])
def list_appointments(doctor_id: int, db: Session = Depends(get_db)):
    return crud.get_appointments_by_doctor(db, doctor_id)