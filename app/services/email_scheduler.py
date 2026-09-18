import smtplib
from email.message import EmailMessage

from loguru import logger

from app.config import settings
from app.database.models import Appointment


def send_appointment_confirmation(appointment: Appointment) -> str:
    subject = "Appointment confirmation"
    body = (
        f"Hello {appointment.patient_name},\n\n"
        f"Your appointment is confirmed for {appointment.date} at {appointment.time}.\n"
        "Please contact the clinic if you need to reschedule.\n\n"
        "Thank you."
    )

    if not settings.email_enabled or not settings.smtp_host:
        logger.info(
            "Email disabled or SMTP not configured. Confirmation for appointment "
            f"{appointment.id} would be sent to {appointment.email}."
        )
        return "skipped"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_email
    message["To"] = appointment.email
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return "sent"
    except Exception as exc:
        logger.exception(f"Failed to send appointment confirmation: {exc}")
        return "failed"


def send_confirmation_for_appointment_id(appointment_id: int) -> str:
    """Sends the confirmation from a background task, using its own session.

    Background tasks run after the response is sent, so the request-scoped ORM
    object is no longer available — only the id is safe to pass along.
    """
    from app.database.database import SessionLocal
    from app.database.models import Appointment as AppointmentModel

    with SessionLocal() as session:
        appointment = session.get(AppointmentModel, appointment_id)
        if appointment is None:
            logger.warning("Appointment {} vanished before its confirmation email", appointment_id)
            return "missing"

        status = send_appointment_confirmation(appointment)
        appointment.confirmation_email_status = status
        session.commit()
        return status
