"""FastAPI Layer 4 API and event gateway."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.api.v1.api import api_router
from backend.core.config import settings
from backend.db.session import SessionLocal, engine
from backend.services.customer_sync import customer_sync
from backend.services.retention_service import retention_service
from backend.ws import alerts_endpoint, camera_frames_endpoint

log = logging.getLogger(__name__)


async def _retention_loop() -> None:
    while True:
        db = SessionLocal()
        try:
            result = retention_service.cleanup(
                db,
                retention_days=settings.VIOLATION_RETENTION_DAYS,
                max_violations=settings.VIOLATION_MAX_COUNT,
                keep_violations=settings.VIOLATION_KEEP_COUNT,
            )
            if result["age_deleted"] or result["capacity_deleted"]:
                log.info("Violation retention cleanup: %s", result)
        except Exception:
            log.exception("Violation retention cleanup failed")
        finally:
            db.close()
        await asyncio.sleep(settings.VIOLATION_RETENTION_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_retention_loop())
    # In customer-host deployments, subscribe to the cloud MQTT event topic
    # so violations flow into the local PostgreSQL that the frontend reads.
    customer_sync.start()
    try:
        yield
    finally:
        customer_sync.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "project": settings.PROJECT_NAME, "version": settings.VERSION}


@app.get("/health/ready", tags=["Health"])
def readiness():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ready", "database": "ready"}


@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await alerts_endpoint(websocket)


@app.websocket("/ws/cameras/{camera_id}")
async def websocket_camera_frames(
    websocket: WebSocket, camera_id: int, overlay: bool = True
):
    await camera_frames_endpoint(websocket, camera_id, overlay)
