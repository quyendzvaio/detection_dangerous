"""
FastAPI backend — the bridge between the AI engine and the React dashboard.

Run (dev):
    uvicorn backend.main:app --reload --port 8080

Skeleton only: routers are registered here as they are implemented.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Industrial Safety AI — API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# TODO(api): include_router for cameras, zones, violations, persons, reports, auth
# TODO(ws): mount WebSocket hub from backend.ws
# TODO(streaming): mount MJPEG routes from backend.streaming
