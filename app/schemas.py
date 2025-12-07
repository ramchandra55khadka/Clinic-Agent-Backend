from typing import List,Optional
from pydantic import BaseModel
from datetime import date,time


#---RAG Query schemas---
class QueryRequest(BaseModel):
    """Request model for the user query"""

    query:str
    top_k:Optional[int]=5
    system_prompt:Optional[str]=None


class QueryResponse(BaseModel):
    response:str
    chunks:Optional[List[dict]]=None

#-----Doctor Schedule schemas----
class DoctorScheduleCreate(BaseModel):
    doctor_name:str
    start_time:time
    end_time:time
    break_start:Optional[time]=None
    break_end:Optional[time]=None
    leave_date:Optional[date]=None
    slot_duration:Optional[int]=20 #default 20 min for duration for each appointment

class DoctorScheduleOut(DoctorScheduleCreate):
    id:int
    class config:
        from_attributes=True

#--Appointment Schemas---
class AppointmentCreate(BaseModel):
    doctor_id:int
    patient_name:str
    age:int
    sex:str
    email:str
    phone:str
    date:date
    time:time



class AppointmentOut(AppointmentCreate):
    id: int

    class Config:
        from_attributes = True

