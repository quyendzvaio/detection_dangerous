from fastapi import APIRouter

from backend.api.v1.endpoints import auth, cameras, internal, reports, violations, zones

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(cameras.router, prefix="/cameras", tags=["Cameras"])
api_router.include_router(violations.router, prefix="/violations", tags=["Violations"])
api_router.include_router(zones.router, prefix="/zones", tags=["Zones"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(internal.router, prefix="/internal", tags=["Internal Events"])
