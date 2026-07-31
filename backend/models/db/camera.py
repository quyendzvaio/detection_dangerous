from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from backend.db.session import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_key = Column(String(100), nullable=False, unique=True, index=True)
    name = Column(String(100), nullable=False)
    source = Column(String(500), nullable=False)
    location_desc = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="OFFLINE", index=True)
    zone_enabled = Column(Boolean, nullable=False, default=True)
    fall_enabled = Column(Boolean, nullable=False, default=True)
    ppe_enabled = Column(Boolean, nullable=False, default=False)
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
