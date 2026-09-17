# from datetime import datetime, timedelta
# from sqlalchemy.orm import Session
# from app.database.models import DoctorSchedule, Appointment

# def check_availability(db: Session, doctor_id: int, date, time):
#     schedule = db.query(DoctorSchedule).filter(DoctorSchedule.id == doctor_id).first()
#     if not schedule:
#         return False

#     # Use slot_duration from doctor schedule, default = 20 minutes
#     duration = schedule.slot_duration or 20  

#     appt_start = datetime.combine(date, time)
#     appt_end = appt_start + timedelta(minutes=duration)

#     schedule_start = datetime.combine(date, schedule.start_time)
#     schedule_end = datetime.combine(date, schedule.end_time)

#     # Check if inside working hours
#     if appt_start < schedule_start or appt_end > schedule_end:
#         return False

#     # Break-time check
#     if schedule.break_start and schedule.break_end:
#         break_start = datetime.combine(date, schedule.break_start)
#         break_end = datetime.combine(date, schedule.break_end)

#         if (appt_start < break_end) and (appt_end > break_start):
#             return False

#     # Check overlapping appointments
#     existing_appts = db.query(Appointment).filter(
#         Appointment.doctor_id == doctor_id,
#         Appointment.date == date
#     ).all()

#     for appt in existing_appts:
#         existing_start = datetime.combine(date, appt.time)
#         existing_end = existing_start + timedelta(minutes=duration)

#         if (appt_start < existing_end) and (appt_end > existing_start):
#             return False

#     return True


from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database.models import DoctorSchedule, Appointment

def check_availability(db: Session, doctor_id: int, date, time):
    """
    Check if a doctor is available for a given date and time.

    Args:
        db (Session): SQLAlchemy session
        doctor_id (int): ID of the doctor
        date (str | datetime.date): Appointment date (YYYY-MM-DD) or date object
        time (str | datetime.time): Appointment time (HH:MM) or time object

    Returns:
        bool: True if available, False otherwise
    """

    # ----------------------------
    # Convert strings to date/time
    # ----------------------------
    if isinstance(date, str):
        date = datetime.strptime(date, "%Y-%m-%d").date()
    if isinstance(time, str):
        time = datetime.strptime(time, "%H:%M").time()

    # ----------------------------
    # Fetch doctor schedule
    # ----------------------------
    schedule = db.query(DoctorSchedule).filter(DoctorSchedule.id == doctor_id).first()
    if not schedule:
        return False

    duration = schedule.slot_duration or 20  # default 20 minutes

    appt_start = datetime.combine(date, time)
    appt_end = appt_start + timedelta(minutes=duration)

    schedule_start = datetime.combine(date, schedule.start_time)
    schedule_end = datetime.combine(date, schedule.end_time)

    # Check if within working hours
    if appt_start < schedule_start or appt_end > schedule_end:
        return False

    # Break-time check
    if schedule.break_start and schedule.break_end:
        break_start = datetime.combine(date, schedule.break_start)
        break_end = datetime.combine(date, schedule.break_end)
        if (appt_start < break_end) and (appt_end > break_start):
            return False

    # Check overlapping appointments
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
