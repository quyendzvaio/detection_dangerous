"""Automatic retention cleanup for persisted violations and their evidence."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.models.db.violation import Violation
from backend.services.storage_service import storage_service

log = logging.getLogger(__name__)


class RetentionService:
    """Delete old violations without allowing evidence blobs to accumulate forever."""

    @staticmethod
    def _delete_candidates(db: Session, violations: list[Violation]) -> int:
        if not violations:
            return 0
        deleted = 0
        for violation in violations:
            keys = {item.object_key for item in violation.evidence_objects if item.object_key}
            keys.update(key for key in (violation.image_storage_key, violation.video_storage_key) if key)
            try:
                if storage_service.is_configured():
                    for key in keys:
                        storage_service.delete_object(key)
            except Exception:
                log.exception("Retention skipped violation %s because evidence deletion failed", violation.id)
                continue
            db.delete(violation)
            deleted += 1
        db.commit()
        return deleted

    @staticmethod
    def cleanup(db: Session, *, retention_days: int, max_violations: int, keep_violations: int) -> dict[str, int]:
        """Apply age retention, then capacity retention."""
        if retention_days <= 0 or max_violations <= 0 or keep_violations < 0:
            raise ValueError("retention limits are invalid")
        if keep_violations >= max_violations:
            raise ValueError("keep_violations must be smaller than max_violations")
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        aged = (db.query(Violation).filter(Violation.detected_time < cutoff)
                .order_by(Violation.detected_time.asc(), Violation.id.asc()).all())
        age_deleted = RetentionService._delete_candidates(db, aged)
        count = db.query(Violation).count()
        capacity_deleted = 0
        if count >= max_violations:
            candidates = (db.query(Violation)
                .order_by(Violation.detected_time.asc(), Violation.id.asc())
                .limit(count - keep_violations).all())
            capacity_deleted = RetentionService._delete_candidates(db, candidates)
        return {"age_deleted": age_deleted, "capacity_deleted": capacity_deleted, "remaining": db.query(Violation).count()}


retention_service = RetentionService()
