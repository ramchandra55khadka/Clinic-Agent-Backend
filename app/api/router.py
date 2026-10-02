"""Aggregated API router.

Every route is exposed both unversioned and under ``settings.api_prefix``
(``/api``) — see :func:`app.main.create_app`.
"""

from fastapi import APIRouter

from app.ai.mcp.server import router as mcp_router
from app.api.routes.appointment import router as appointment_router
from app.api.routes.auth import router as auth_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.doctor_info import router as doctor_info_router
from app.api.routes.health import router as health_router
from app.api.routes.memories import router as memories_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(appointment_router)
api_router.include_router(doctor_info_router)
api_router.include_router(mcp_router)
api_router.include_router(memories_router)
api_router.include_router(conversations_router)
