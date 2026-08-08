from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models.db.evidence import EvidenceObject
from backend.models.db.violation import Violation
from backend.models.schemas.evidence import (
    EvidenceCompleteRequest,
    EvidenceFailRequest,
    EvidenceLifecycleResponse,
    EvidenceObjectOut,
    EvidencePresignRequest,
    EvidencePresignResponse,
    EvidenceUploadOut,
)
from backend.services.storage_service import storage_service

_CONTENT_EXTENSIONS = {"image/jpeg": "jpg", "video/mp4": "mp4"}
_EXPECTED_KINDS = {
    "PPE_VIOLATION": {"IMAGE"},
    "RESTRICTED_ZONE": {"IMAGE"},
    "FALL_DETECTED": {"IMAGE", "VIDEO"},
    "FALL_SUSPECTED": {"IMAGE"},
}


class EvidenceService:
    @staticmethod
    def _get_violation(db: Session, event_id: UUID, lock: bool = False) -> Violation:
        query = db.query(Violation).filter(Violation.event_id == event_id)
        if lock:
            query = query.with_for_update()
        violation = query.first()
        if violation is None:
            raise HTTPException(status_code=404, detail="Safety event not found")
        return violation

    @staticmethod
    def _validate_expected_kinds(violation: Violation, request: EvidencePresignRequest) -> None:
        requested = {item.kind for item in request.objects}
        expected = _EXPECTED_KINDS.get(violation.violation_type)
        if expected is None or requested != expected:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{violation.violation_type} requires evidence kinds "
                    f"{sorted(expected or set())}"
                ),
            )

    @staticmethod
    def _object_key(violation: Violation, kind: str, content_type: str) -> str:
        timestamp = violation.detected_time
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)
        extension = _CONTENT_EXTENSIONS[content_type]
        return (
            f"evidence/camera-{violation.camera_id}/"
            f"{timestamp:%Y/%m/%d}/{violation.event_id}/{kind.lower()}.{extension}"
        )

    def request_uploads(
        self, db: Session, event_id: UUID, request: EvidencePresignRequest
    ) -> EvidencePresignResponse:
        violation = self._get_violation(db, event_id, lock=True)
        self._validate_expected_kinds(violation, request)
        existing_by_kind = {item.kind: item for item in violation.evidence_objects}
        if any(item.status == "READY" for item in existing_by_kind.values()):
            raise HTTPException(status_code=409, detail="Evidence is already uploaded")

        outputs: list[EvidenceUploadOut] = []
        now = datetime.now(timezone.utc)
        for spec in request.objects:
            evidence = existing_by_kind.get(spec.kind)
            object_key = self._object_key(violation, spec.kind, spec.content_type)
            if evidence is None:
                evidence = EvidenceObject(
                    violation_id=violation.id,
                    kind=spec.kind,
                    object_key=object_key,
                    content_type=spec.content_type,
                )
                db.add(evidence)
                db.flush()
            elif evidence.content_type != spec.content_type:
                raise HTTPException(status_code=409, detail="Evidence content type changed")

            upload_lease = storage_service.create_upload_lease(
                object_key, spec.content_type
            )
            evidence.object_key = object_key
            evidence.status = "PROCESSING"
            evidence.size_bytes = spec.size_bytes
            evidence.etag = None
            evidence.failure_reason = None
            evidence.uploaded_at = None
            evidence.upload_expires_at = now + timedelta(
                seconds=upload_lease.expires_in_seconds
            )
            outputs.append(
                EvidenceUploadOut(
                    evidence_id=evidence.id,
                    kind=spec.kind,
                    object_key=object_key,
                    upload_url=upload_lease.url,
                    upload_headers=upload_lease.headers,
                    content_type=spec.content_type,
                    expires_in_seconds=upload_lease.expires_in_seconds,
                )
            )

        violation.evidence_status = "PROCESSING"
        db.commit()
        return EvidencePresignResponse(event_id=event_id, uploads=outputs)

    def complete_uploads(
        self, db: Session, event_id: UUID, request: EvidenceCompleteRequest
    ) -> EvidenceLifecycleResponse:
        violation = self._get_violation(db, event_id, lock=True)
        evidence_by_id = {item.id: item for item in violation.evidence_objects}
        verified: dict[int, dict[str, object]] = {}
        for item in request.objects:
            evidence = evidence_by_id.get(item.evidence_id)
            if evidence is None:
                raise HTTPException(status_code=404, detail="Evidence object not found for event")
            if evidence.size_bytes is not None and evidence.size_bytes != item.size_bytes:
                raise HTTPException(status_code=409, detail="Uploaded evidence size changed")
            verified[evidence.id] = storage_service.verify_uploaded_object(
                evidence.object_key, item.size_bytes, evidence.content_type
            )

        now = datetime.now(timezone.utc)
        for item in request.objects:
            evidence = evidence_by_id[item.evidence_id]
            metadata = verified[evidence.id]
            evidence.status = "READY"
            evidence.size_bytes = item.size_bytes
            evidence.etag = metadata.get("etag") or (
                item.etag.strip('"') if item.etag else None
            )
            evidence.failure_reason = None
            evidence.uploaded_at = now
            if evidence.kind == "IMAGE":
                violation.image_storage_key = evidence.object_key
            elif evidence.kind == "VIDEO":
                violation.video_storage_key = evidence.object_key

        self._update_aggregate(violation)
        db.commit()
        db.refresh(violation)
        return self._lifecycle_response(violation)

    def fail_uploads(
        self, db: Session, event_id: UUID, request: EvidenceFailRequest
    ) -> EvidenceLifecycleResponse:
        violation = self._get_violation(db, event_id, lock=True)
        evidence_by_id = {item.id: item for item in violation.evidence_objects}
        for item in request.objects:
            evidence = evidence_by_id.get(item.evidence_id)
            if evidence is None:
                raise HTTPException(status_code=404, detail="Evidence object not found for event")
            if evidence.status != "READY":
                evidence.status = "FAILED"
                evidence.failure_reason = item.reason
        self._update_aggregate(violation)
        db.commit()
        db.refresh(violation)
        return self._lifecycle_response(violation)

    @staticmethod
    def _update_aggregate(violation: Violation) -> None:
        statuses = {item.status for item in violation.evidence_objects}
        if "FAILED" in statuses:
            violation.evidence_status = "FAILED"
        elif statuses and statuses == {"READY"}:
            violation.evidence_status = "READY"
        else:
            violation.evidence_status = "PROCESSING"

    @staticmethod
    def _lifecycle_response(violation: Violation) -> EvidenceLifecycleResponse:
        ready = violation.evidence_status == "READY"
        return EvidenceLifecycleResponse(
            event_id=violation.event_id,
            evidence_status=violation.evidence_status,
            image_storage_key=violation.image_storage_key,
            video_storage_key=violation.video_storage_key,
            image_download_url=(
                storage_service.generate_signed_download(
                    violation.image_storage_key
                )
                if ready
                and violation.image_storage_key
                and storage_service.is_configured()
                else None
            ),
            video_download_url=(
                storage_service.generate_signed_download(
                    violation.video_storage_key
                )
                if ready
                and violation.video_storage_key
                and storage_service.is_configured()
                else None
            ),
            objects=[
                EvidenceObjectOut.model_validate(item)
                for item in sorted(violation.evidence_objects, key=lambda row: row.id)
            ],
        )


evidence_service = EvidenceService()
