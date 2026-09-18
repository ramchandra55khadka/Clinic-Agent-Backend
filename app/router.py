from fastapi import APIRouter

from app.ai.mcp.server import router as mcp_router
from app.routers.appointment import router as appointment_router
from app.routers.doctor_info import router as doctor_info_router

router = APIRouter()
router.include_router(appointment_router)
router.include_router(doctor_info_router)
router.include_router(mcp_router)
