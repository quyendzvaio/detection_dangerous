from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import relationship

from backend.db.session import Base


class SystemEvent(Base):
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    event_id = Column(Uuid(as_uuid=True), nullable=False, unique=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, index=True)
    reason = Column(String(500), nullable=True)
    source = Column(String(100), nullable=False, default="SUPERVISOR")
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    camera = relationship("Camera", back_populates="system_events")
