"""SQLAlchemy models — one module per table.

This package ``__init__`` imports every model module so that simply importing
``app.models`` registers them all on ``Base.metadata`` (used by Alembic
autogenerate and ``Base.metadata.create_all``). Application code should import a
specific model from its module, e.g. ``from app.models.user_account
import UserAccount``.
"""

from app.models.appointment import Appointment
from app.models.audit_log import AuditLog
from app.models.conversation import Conversation, ConversationMessage
from app.models.doctor import Doctor
from app.models.doctor_education import DoctorEducation
from app.models.doctor_schedule import DoctorSchedule
from app.models.long_term_memory import LongTermMemory
from app.models.patient import Patient
from app.models.user_account import RefreshToken, UserAccount
from app.models.user_profile import UserProfile

__all__ = [
    "Appointment",
    "AuditLog",
    "Conversation",
    "ConversationMessage",
    "Doctor",
    "DoctorEducation",
    "DoctorSchedule",
    "LongTermMemory",
    "Patient",
    "RefreshToken",
    "UserAccount",
    "UserProfile",
]
