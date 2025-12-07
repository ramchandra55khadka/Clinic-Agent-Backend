from sqlalchemy.orm import Session
from .models import Appointment,DoctorSchedule
from app.schemas import AppointmentCreate,DoctorScheduleCreate



# -------------------- Doctor Schedule CRUD --------------------

def create_doctor_schedule(db: Session, schedule: DoctorScheduleCreate):
    db_schedule = DoctorSchedule(**schedule.dict())
    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)
    return db_schedule


def get_doctor_schedule(db: Session, doctor_id: int):
    return db.query(DoctorSchedule).filter(
        DoctorSchedule.id == doctor_id
    ).first()

def get_all_doctor_schedules(db: Session):
    return db.query(DoctorSchedule).all()

def update_doctor_schedule(db: Session, doctor_id: int, schedule: DoctorScheduleCreate):
    db_schedule = db.query(DoctorSchedule).filter(
        DoctorSchedule.id == doctor_id
    ).first()

    if not db_schedule:
        return None

    for key, value in schedule.dict().items():
        setattr(db_schedule, key, value)

    db.commit()
    db.refresh(db_schedule)
    return db_schedule


def delete_doctor_schedule(db: Session, doctor_id: int):
    db_schedule = db.query(DoctorSchedule).filter(
        DoctorSchedule.id == doctor_id
    ).first()
    if not db_schedule:
        return False
    db.delete(db_schedule)
    db.commit()
    return True


# -------------------- Appointment CRUD --------------------

def create_appointment(db: Session, appointment: AppointmentCreate):
    db_appointment = Appointment(**appointment.dict())
    db.add(db_appointment)
    db.commit()
    db.refresh(db_appointment)
    return db_appointment


def get_appointments_by_doctor(db: Session, doctor_id: int):
    return db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id
    ).all()