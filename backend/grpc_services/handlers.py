import json
from typing import Dict, Any
from backend.db.session import SessionLocal
from backend.services.violation_service import violation_service
from backend.models.schemas.violation import ViolationCreate
from backend.ws import manager


def handle_detection_event(event_dict: Dict[str, Any]) -> int:
    """
    Process incoming detection event from AI stream:
    1. Save to DB violations table
    2. Broadcast to connected WebSocket clients real-time
    """
    db = SessionLocal()
    try:
        ai_metadata = None
        if event_dict.get("ai_metadata_json"):
            try:
                ai_metadata = json.loads(event_dict["ai_metadata_json"])
            except Exception:
                ai_metadata = {}

        violation_in = ViolationCreate(
            camera_id=event_dict.get("camera_id", 1),
            violation_type=event_dict.get("violation_type", "UNKNOWN"),
            severity_level=event_dict.get("severity_level", "WARNING"),
            worker_code=event_dict.get("worker_code"),
            video_path=event_dict.get("video_path"),
            image_path=event_dict.get("image_path"),
            ai_metadata=ai_metadata
        )
        created_violation = violation_service.create_violation(db, violation_in)

        # Broadcast real-time alert via WebSocket manager
        import asyncio
        alert_payload = {
            "type": "NEW_VIOLATION",
            "violation_id": created_violation.id,
            "camera_id": created_violation.camera_id,
            "violation_type": created_violation.violation_type,
            "severity_level": created_violation.severity_level,
            "detected_time": str(created_violation.detected_time)
        }
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(manager.broadcast(alert_payload))
        except Exception:
            pass

        return created_violation.id
    finally:
        db.close()
