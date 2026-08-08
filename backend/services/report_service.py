from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.models.db.violation import Violation
from backend.models.db.camera import Camera
from backend.models.db.user import User
from backend.models.schemas.report import (
    ReportSummaryOut,
    ViolationTypeSummary,
    CameraViolationSummary
)


class ReportService:
    @staticmethod
    def get_summary(db: Session, tenant_id: int) -> ReportSummaryOut:
        total_violations = (
            db.query(Violation)
            .filter(Violation.deleted_at.is_(None), Violation.tenant_id == tenant_id)
            .count()
        )
        total_cameras = (
            db.query(Camera)
            .filter(Camera.deleted_at.is_(None), Camera.tenant_id == tenant_id)
            .count()
        )
        total_users = (
            db.query(User).filter(User.is_active == True, User.tenant_id == tenant_id).count()
        )

        # Group by violation_type
        type_counts = (
            db.query(Violation.violation_type, func.count(Violation.id))
            .filter(Violation.deleted_at.is_(None), Violation.tenant_id == tenant_id)
            .group_by(Violation.violation_type)
            .all()
        )
        violations_by_type = [
            ViolationTypeSummary(violation_type=v_type, count=cnt)
            for v_type, cnt in type_counts
        ]

        # Group by camera
        cam_counts = (
            db.query(Camera.id, Camera.name, func.count(Violation.id))
            .join(Violation, Violation.camera_id == Camera.id)
            .filter(
                Camera.deleted_at.is_(None),
                Camera.tenant_id == tenant_id,
                Violation.deleted_at.is_(None),
                Violation.tenant_id == tenant_id,
            )
            .group_by(Camera.id, Camera.name)
            .all()
        )
        violations_by_camera = [
            CameraViolationSummary(camera_id=c_id, camera_name=c_name, count=cnt)
            for c_id, c_name, cnt in cam_counts
        ]

        return ReportSummaryOut(
            total_violations=total_violations,
            total_cameras=total_cameras,
            total_users=total_users,
            violations_by_type=violations_by_type,
            violations_by_camera=violations_by_camera
        )


report_service = ReportService()
