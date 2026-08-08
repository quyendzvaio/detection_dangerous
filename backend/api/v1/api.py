from fastapi import APIRouter
from backend.core.config import settings

from backend.api.v1.endpoints import auth, cameras, control_plane, internal, reports, violations, zones

api_router = APIRouter()
if settings.DEPLOYMENT_ROLE != "cloud-control-plane":
    api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
    api_router.include_router(cameras.router, prefix="/cameras", tags=["Cameras"])
    api_router.include_router(violations.router, prefix="/violations", tags=["Violations"])
    api_router.include_router(zones.router, prefix="/zones", tags=["Zones"])
    api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
    api_router.include_router(internal.router, prefix="/internal", tags=["Internal Events"])
api_router.include_router(control_plane.router, prefix="/control", tags=["SaaS Control Plane"])
