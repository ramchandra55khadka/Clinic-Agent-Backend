from fastapi import APIRouter

from app.ai.mcp.server import router as mcp_router
from app.routers.appointment import router as appointment_router
from app.routers.auth import router as auth_router
from app.routers.doctor_info import router as doctor_info_router
from app.routers.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(appointment_router)
api_router.include_router(doctor_info_router)
api_router.include_router(mcp_router)
