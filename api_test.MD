Postman API Tests
1️⃣ Create Doctor Schedule

Method: POST

URL: http://127.0.0.1:8000/doctor-schedule/

Body (raw JSON, Content-Type: application/json):

{
  "doctor_name": "Dr. Ramchandra",
  "start_time": "09:00:00",
  "end_time": "17:00:00",
  "break_start": "12:30:00",
  "break_end": "13:30:00",
  "leave_date": "2025-12-25"
}


Expected Response (200 OK):

{
  "id": 1,
  "doctor_name": "Dr. Ramchandra",
  "start_time": "09:00:00",
  "end_time": "17:00:00",
  "break_start": "12:30:00",
  "break_end": "13:30:00",
  "leave_date": "2025-12-25"
}

2️⃣ Get Doctor Schedule
To get all the schedule:=>http://127.0.0.1:8000/doctor-schedule/

Method: GET

URL: http://127.0.0.1:8000/doctor-schedule/1

Expected Response:

{
  "id": 1,
  "doctor_name": "Dr. Ramchandra",
  "start_time": "09:00:00",
  "end_time": "17:00:00",
  "break_start": "12:30:00",
  "break_end": "13:30:00",
  "leave_date": "2025-12-25"
}

3️⃣ Update Doctor Schedule

Method: PUT

URL: http://127.0.0.1:8000/doctor-schedule/1

Body:

{
  "doctor_name": "Dr. Ramchandra",
  "start_time": "10:00:00",
  "end_time": "18:00:00",
  "break_start": "13:00:00",
  "break_end": "14:00:00",
  "leave_date": "2025-12-31"
}


Expected Response: Updated schedule with same id.

4️⃣ Delete Doctor Schedule

Method: DELETE

URL: http://127.0.0.1:8000/doctor-schedule/1

Expected Response:

{
  "message": "Doctor schedule deleted successfully"
}

5️⃣ Create Appointment

Method: POST

URL: http://127.0.0.1:8000/appointments/

Body:

{
  "doctor_id": 1,
  "patient_name": "Ramchandra Khadka",
  "age": 30,
  "sex": "Male",
  "email": "ramchandra@example.com",
  "phone": "9866835892",
  "date": "2025-12-10",
  "time": "10:30:00"
}


Expected Response (200 OK):

{
  "id": 1,
  "doctor_id": 1,
  "patient_name": "Ramchandra Khadka",
  "age": 30,
  "sex": "Male",
  "email": "ramchandra@example.com",
  "phone": "9866835892",
  "date": "2025-12-10",
  "time": "10:30:00",
  "doctor": {
    "id": 1,
    "doctor_name": "Dr. Ramchandra",
    "start_time": "10:00:00",
    "end_time": "18:00:00",
    "break_start": "13:00:00",
    "break_end": "14:00:00",
    "leave_date": "2025-12-31"
  }
}


Error Example: If doctor unavailable or slot booked:

{
  "detail": "Doctor is not available at this time or slot already booked."
}

6️⃣ List Appointments by Doctor

Method: GET

URL: http://127.0.0.1:8000/appointments/1

Expected Response:

[
  {
    "id": 1,
    "doctor_id": 1,
    "patient_name": "Ramchandra Khadka",
    "age": 30,
    "sex": "Male",
    "email": "ramchandra@example.com",
    "phone": "9866835892",
    "date": "2025-12-10",
    "time": "10:30:00",
    "doctor": {
      "id": 1,
      "doctor_name": "Dr. Ramchandra",
      "start_time": "10:00:00",
      "end_time": "18:00:00",
      "break_start": "13:00:00",
      "break_end": "14:00:00",
      "leave_date": "2025-12-31"
    }
  }
]
