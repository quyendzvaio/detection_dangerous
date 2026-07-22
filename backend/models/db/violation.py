from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from backend.db.session import Base


class Violation(Base):
    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    detected_time = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    violation_type = Column(String(50), nullable=False)  # PPE_NO_HELMET, RESTRICTED_ZONE, FALL_DETECTED
    severity_level = Column(String(20), default="WARNING")  # INFO, WARNING, DANGER, CRITICAL
    worker_code = Column(String(50), nullable=True)  # Re-ID employee code/id
    video_bucket = Column(String(100), nullable=True)  # R2 bucket name
    video_path = Column(String(255), nullable=True)   # R2 object key for video clip
    image_path = Column(String(255), nullable=True)   # R2 object key for snapshot image
    status = Column(String(20), default="NEW")         # NEW, REVIEWED, DISMISSED, RESOLVED
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    ai_metadata = Column(JSON, nullable=True)          # Extra bounding box/keypoints/confidence info
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    camera = relationship("Camera", back_populates="violations")
    reviewer = relationship("User", back_populates="reviewed_violations")
