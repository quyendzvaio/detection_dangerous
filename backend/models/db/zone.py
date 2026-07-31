from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship

from backend.db.session import Base


class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    polygon_json = Column(JSON, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    camera = relationship("Camera", back_populates="zones")
    violations = relationship("Violation", back_populates="zone")
