"""
FastAPI backend — Industrial Safety AI Analytics API & Gateway.

Run (dev):
    uvicorn backend.main:app --reload --port 8080
"""
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.db.session import engine
from backend.db.base import Base
from backend.api.v1.api import api_router
from backend.ws import alerts_endpoint
from backend.streaming import mjpeg_generator

# Create DB tables automatically if they don't exist yet
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Healthcheck endpoint
@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "ok",
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION
    }

# Register API v1 routes
app.include_router(api_router, prefix=settings.API_V1_STR)

# Register WebSocket route for real-time alerts
@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await alerts_endpoint(websocket)

# Register MJPEG stream route
@app.get("/stream/{camera_id}", tags=["Streaming"])
def camera_stream(camera_id: int):
    """Serve MJPEG stream for live video preview."""
    def get_dummy_frame():
        return None
    return mjpeg_generator(get_dummy_frame)
