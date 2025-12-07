from sqlalchemy.orm import Session
from .models import Appointment,DoctorSchedule
from app.schemas import AppointmentCreate,DoctorScheduleCreate
from datetime import datetime,timedelta



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



def check_availability(db: Session, doctor_id: int, date, time):
    schedule = db.query(DoctorSchedule).filter(DoctorSchedule.id == doctor_id).first()
    if not schedule:
        return False

    duration = schedule.slot_duration or 20  # use doctor’s slot_duration
    appt_start = datetime.combine(date, time)  #appointment start
    appt_end = appt_start + timedelta(minutes=duration)  #appointment end

    schedule_start = datetime.combine(date, schedule.start_time)
    schedule_end = datetime.combine(date, schedule.end_time)

    # check if appointment is within working hours
    if appt_start < schedule_start or appt_end > schedule_end:
        return False

    # check break time
    if schedule.break_start and schedule.break_end:
        break_start = datetime.combine(date, schedule.break_start)
        break_end = datetime.combine(date, schedule.break_end)
        if (appt_start < break_end) and (appt_end > break_start):
            return False

    # check overlapping appointments
    existing_appts = db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.date == date
    ).all()

    for appt in existing_appts:
        existing_start = datetime.combine(date, appt.time)
        existing_end = existing_start + timedelta(minutes=duration)
        if (appt_start < existing_end) and (appt_end > existing_start):
            return False

    return True