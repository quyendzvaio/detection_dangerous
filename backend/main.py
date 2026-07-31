"""FastAPI Layer 4 API and event gateway."""
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.api.v1.api import api_router
from backend.core.config import settings
from backend.db.session import engine
from backend.ws import alerts_endpoint

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
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
