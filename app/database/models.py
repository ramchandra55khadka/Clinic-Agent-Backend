from sqlalchemy import Column,Integer,String,Date,Time,ForeignKey
from sqlalchemy.orm import relationship
from .database import Base
class DoctorSchedule(Base):
    __tablename__="doctor_schedule"

    id=Column(Integer,primary_key=True,index=True)
    doctor_name=Column(String,nullable=False)
    start_time=Column(Time,nullable=False)
    end_time = Column(Time, nullable=False)
    break_start = Column(Time, nullable=True)
    break_end = Column(Time, nullable=True)
    leave_date = Column(Date, nullable=True)
    slot_duration=Column(Integer,default=20) #duration of each appointment in minute

class Appointment(Base):
    __tablename__="appointments"

    id=Column(Integer,primary_key=True,index=True)
    doctor_id = Column(Integer, ForeignKey("doctor_schedule.id"))
    patient_name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    sex = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    time = Column(Time, nullable=False)
    doctor=relationship("DoctorSchedule")