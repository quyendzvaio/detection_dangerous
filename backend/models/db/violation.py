from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import relationship

from backend.db.session import Base


class Violation(Base):
    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    event_id = Column(Uuid(as_uuid=True), nullable=False, unique=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    track_id = Column(String(150), nullable=False, index=True)
    detected_time = Column(DateTime(timezone=True), nullable=False, index=True)
    violation_type = Column(String(50), nullable=False, index=True)
    severity_level = Column(String(20), nullable=False, index=True)

    confidence = Column(Float, nullable=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True, index=True)
    violation_codes = Column(JSON, nullable=True)

    evidence_status = Column(String(20), nullable=False, default="PROCESSING")
    image_storage_key = Column(String(1024), nullable=True)
    video_storage_key = Column(String(1024), nullable=True)

    status = Column(String(20), nullable=False, default="NEW", index=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    camera = relationship("Camera", back_populates="violations")
    zone = relationship("Zone", back_populates="violations")
    reviewer = relationship("User", back_populates="reviewed_violations")
    evidence_objects = relationship(
        "EvidenceObject", back_populates="violation", cascade="all, delete-orphan"
    )
