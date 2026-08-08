from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from backend.db.session import Base


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('USB', 'RTSP', 'HTTP', 'VIDEO_FILE')",
            name="ck_cameras_source_type",
        ),
        CheckConstraint(
            "config_status IN ('PENDING', 'APPLIED', 'FAILED', 'OFFLINE')",
            name="ck_cameras_config_status",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Nullable during migration so the existing customer-host database can be
    # upgraded before it is enrolled into a SaaS tenant.
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    edge_device_id = Column(Integer, ForeignKey("edge_devices.id"), nullable=True, index=True)
    stream_id = Column(Integer, ForeignKey("streams.id"), nullable=True, index=True)
    camera_key = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(100), nullable=False)
    source = Column(String(500), nullable=False)
    source_type = Column(String(20), nullable=False, default="USB")
    location_desc = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="OFFLINE", index=True)
    zone_enabled = Column(Boolean, nullable=False, default=True)
    fall_enabled = Column(Boolean, nullable=False, default=True)
    ppe_enabled = Column(Boolean, nullable=False, default=False)
    config_revision = Column(BigInteger, nullable=False, default=1)
    applied_revision = Column(BigInteger, nullable=True)
    applied_zone_enabled = Column(Boolean, nullable=True)
    applied_fall_enabled = Column(Boolean, nullable=True)
    applied_ppe_enabled = Column(Boolean, nullable=True)
    config_status = Column(String(20), nullable=False, default="OFFLINE")
    config_error = Column(String(1000), nullable=True)
    config_applied_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    processing_fps = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)
    last_frame_at = Column(DateTime(timezone=True), nullable=True)
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

    violations = relationship("Violation", back_populates="camera")
    zones = relationship("Zone", back_populates="camera", cascade="all, delete-orphan")
    system_events = relationship("SystemEvent", back_populates="camera")
